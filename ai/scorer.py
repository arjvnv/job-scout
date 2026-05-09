from __future__ import annotations

import concurrent.futures
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from models import JobListing

RESUME_TRUNCATE_CHARS: int = 6_000
DEFAULT_BATCH_SIZE: int = 10
MAX_WORKERS: int = 4

_SYSTEM_PROMPT = (
    "You score how well a candidate's resume matches job listings. Given a resume "
    "and a list of listings (each with title, company, location, type), return STRICT "
    "JSON only — no prose. For each listing:\n"
    "  - score: integer 0-100. 90+ = strong fit; 70-89 = good fit; 50-69 = stretch; "
    "below 50 = weak fit. Score on title alignment, seniority, skill overlap inferred "
    "from title/company, and location compatibility.\n"
    "  - top_missing_skills: array of up to 3 short skill names a candidate would "
    'likely need that are NOT evident in the resume (lowercased, e.g. "kubernetes").\n'
    'Output schema: {"results":[{"index":int,"score":int,"top_missing_skills":[str]}]}'
)

_TIPS_SYSTEM_PROMPT = (
    "You are a resume coach. Given (a) the resume and (b) the top missing skills "
    "aggregated from the listings, output exactly 2-3 short, specific, actionable "
    "bullet points (one sentence each) the candidate should consider. No preamble, "
    'no closing line. Plain text bullets prefixed with "• ".'
)


@dataclass
class ScoringResult:
    scores: dict[int, int] = field(default_factory=dict)
    skills_gap: list[tuple[str, int]] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    failed_batches: int = 0
    total_batches: int = 0


def score_listings(
    listings: list[JobListing],
    resume_text: str,
    llm: Any,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ScoringResult:
    """Score each listing against the resume using batched LLM calls."""
    if not listings or not resume_text.strip():
        return ScoringResult()

    truncated_resume = resume_text[:RESUME_TRUNCATE_CHARS]
    batches: list[tuple[int, list[JobListing]]] = []
    for start in range(0, len(listings), batch_size):
        batches.append((start, listings[start : start + batch_size]))

    scores: dict[int, int] = {}
    missing_counter: Counter[str] = Counter()
    failed = 0

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(MAX_WORKERS, len(batches))
    ) as executor:
        futures = {
            executor.submit(_score_batch, llm, truncated_resume, start, batch): start
            for start, batch in batches
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                batch_scores, batch_missing = future.result()
                scores.update(batch_scores)
                missing_counter.update(batch_missing)
            except Exception:
                failed += 1

    skills_gap = missing_counter.most_common(3)
    tips: list[str] = []
    if skills_gap:
        try:
            tips = _generate_tips(llm, truncated_resume, missing_counter.most_common(5))
        except Exception:
            tips = []

    return ScoringResult(
        scores=scores,
        skills_gap=skills_gap,
        tips=tips,
        failed_batches=failed,
        total_batches=len(batches),
    )


def _score_batch(
    llm: Any,
    resume_text: str,
    start_index: int,
    batch: list[JobListing],
) -> tuple[dict[int, int], list[str]]:
    from langchain_core.messages import HumanMessage, SystemMessage

    listings_block = "\n".join(
        f"{i + 1}. {l.title} | {l.company} | {l.location} | {l.job_type}"
        for i, l in enumerate(batch)
    )
    user_prompt = (
        f"RESUME:\n<<<\n{resume_text}\n>>>\n\nLISTINGS:\n{listings_block}"
    )
    response = llm.invoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
    )
    content = _extract_text(response)
    parsed = _parse_json(content)
    if not parsed or "results" not in parsed:
        return {}, []

    batch_scores: dict[int, int] = {}
    batch_missing: list[str] = []
    for entry in parsed.get("results", []):
        if not isinstance(entry, dict):
            continue
        idx = entry.get("index")
        score = entry.get("score")
        if not isinstance(idx, int) or not isinstance(score, int):
            continue
        # Convert 1-based batch index to absolute list index.
        abs_idx = start_index + (idx - 1)
        if 0 <= abs_idx < start_index + len(batch):
            batch_scores[abs_idx] = max(0, min(100, score))
        for skill in entry.get("top_missing_skills", []) or []:
            if isinstance(skill, str) and skill.strip():
                batch_missing.append(skill.strip().lower())
    return batch_scores, batch_missing


def _generate_tips(
    llm: Any,
    resume_text: str,
    top_missing: list[tuple[str, int]],
) -> list[str]:
    from langchain_core.messages import HumanMessage, SystemMessage

    skills_str = ", ".join(f"{s} ({n})" for s, n in top_missing)
    user_prompt = (
        f"RESUME:\n<<<\n{resume_text}\n>>>\n\nTOP MISSING SKILLS:\n{skills_str}"
    )
    response = llm.invoke(
        [
            SystemMessage(content=_TIPS_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
    )
    content = _extract_text(response).strip()
    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    cleaned: list[str] = []
    for ln in lines:
        if ln.startswith("•"):
            ln = ln.lstrip("•").strip()
        elif ln.startswith(("-", "*")):
            ln = ln[1:].strip()
        if ln:
            cleaned.append(ln)
    return cleaned[:3]


def _extract_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _parse_json(content: str) -> dict | None:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Strip a fenced code block if the model wrapped its JSON.
    fence = re.search(r"```(?:json)?\s*(.*?)```", content, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1).strip())
        except json.JSONDecodeError:
            pass
    # Fall back to first balanced object substring.
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
