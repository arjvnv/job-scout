from __future__ import annotations

import re

from models import JobListing


_ABBREVIATION_EXPANSIONS: dict[str, str] = {
    "swe": "software engineer",
    "sde": "software development engineer",
    "pm": "product manager",
    "tpm": "technical program manager",
    "epm": "engineering program manager",
    "ds": "data scientist",
    "da": "data analyst",
    "de": "data engineer",
    "ba": "business analyst",
    "ml": "machine learning",
    "mle": "machine learning engineer",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "cv": "computer vision",
    "ux": "ux designer",
    "ui": "ui designer",
    "sre": "site reliability engineer",
    "devops": "devops engineer",
    "qa": "qa engineer",
    "sdet": "software development engineer in test",
    "fe": "frontend engineer",
    "be": "backend engineer",
    "fs": "full stack engineer",
    "ios": "ios engineer",
    "android": "android engineer",
    "sec": "security engineer",
    "cto": "chief technology officer",
    "ciso": "chief information security officer",
    "cfo": "chief financial officer",
    "coo": "chief operating officer",
}


_LEVEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("intern", re.compile(r"\b(intern|internship|co-?op)\b", re.IGNORECASE)),
    ("lead", re.compile(r"\b(lead|principal|director|head of|vp|vice president|chief|staff)\b", re.IGNORECASE)),
    ("senior", re.compile(r"\b(senior|sr\.?|iii)\b", re.IGNORECASE)),
    ("mid", re.compile(r"\b(mid|mid-?level|ii)\b", re.IGNORECASE)),
    ("junior", re.compile(r"\b(junior|jr\.?|entry|entry-?level|associate)\b|\bi\b\s*$", re.IGNORECASE)),
]


def expand_query(query: str) -> tuple[str, bool]:
    stripped = query.strip().lower()
    if not stripped:
        return stripped, False
    tokens = stripped.split()
    expanded_tokens: list[str] = []
    changed = False
    for token in tokens:
        replacement = _ABBREVIATION_EXPANSIONS.get(token)
        if replacement is not None:
            expanded_tokens.append(replacement)
            changed = True
        else:
            expanded_tokens.append(token)
    return " ".join(expanded_tokens), changed


def normalize_query(query: str) -> str:
    return expand_query(query)[0]


def filter_by_relevance(
    listings: list[JobListing], query: str
) -> list[JobListing]:
    normalized = normalize_query(query)
    words = [w for w in normalized.split() if len(w) >= 3]
    if not words:
        return listings

    return [
        listing
        for listing in listings
        if any(word in listing.title.lower() for word in words)
    ]


def infer_job_type_from_title(title: str) -> str | None:
    """Return 'internship' if the title clearly signals an intern role, else None."""
    lower = title.lower()
    if "intern" in lower:
        return "internship"
    return None


def infer_level_from_title(title: str) -> str | None:
    if not title:
        return None
    for level, pattern in _LEVEL_PATTERNS:
        if pattern.search(title):
            return level
    return None
