from __future__ import annotations

import os
import webbrowser
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from rich.console import Console

from config import DEFAULT_LIMIT, SOURCE_REGISTRY
from models import JobListing
from output.csv_writer import write_csv
from output.table import render_table
from search.pipeline import run_pipeline
from search.query import normalize_query


@dataclass
class ChatState:
    console: Console
    llm: Any
    results: list[JobListing] = field(default_factory=list)
    last_query: str | None = None
    resume_text: str | None = None
    resume_path: str | None = None

    def has_resume(self) -> bool:
        return bool(self.resume_text and self.resume_text.strip())

    def summary(self) -> str:
        parts = [
            f"results loaded: {len(self.results)}",
            f"last query: {self.last_query!r}" if self.last_query else "last query: none",
            f"resume loaded: {'yes' if self.has_resume() else 'no'}",
        ]
        return " | ".join(parts)


class SearchJobsArgs(BaseModel):
    query: str = Field(..., description="Search keywords, e.g. 'ml engineer'")
    job_type: Literal["full-time", "internship", "research", "contract", "any"] = Field(
        "any", description="Filter by job type."
    )
    location: str | None = Field(None, description="City, country, or 'remote'.")
    limit: int = Field(DEFAULT_LIMIT, description="Max results per source.")


class FilterArgs(BaseModel):
    job_type: str | None = Field(None, description="Exact job type to keep.")
    location_contains: str | None = Field(None, description="Substring filter on location.")
    company_contains: str | None = Field(None, description="Substring filter on company.")
    keyword: str | None = Field(None, description="Substring filter on title.")


class MatchArgs(BaseModel):
    pass


class OpenJobArgs(BaseModel):
    index: int = Field(..., description="1-based result index to open.")


class ShowReqArgs(BaseModel):
    index: int = Field(..., description="1-based result index to summarize.")


class ExportArgs(BaseModel):
    path: str = Field(..., description="CSV destination path; ~ is expanded.")


def build_tools(state: ChatState) -> list[Any]:
    from langchain_core.tools import StructuredTool

    def search_jobs(
        query: str,
        job_type: str = "any",
        location: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> str:
        normalized = normalize_query(query)
        effective_type = None if job_type == "any" else job_type
        with state.console.status("[dim]searching…[/dim]"):
            listings = run_pipeline(
                SOURCE_REGISTRY,
                normalized,
                effective_type,
                location,
                limit,
                state.console,
            )
        state.results = listings
        state.last_query = query

        show_match = False
        if state.has_resume() and listings:
            show_match = _score_state_results(state)

        if show_match:
            state.results.sort(
                key=lambda l: (l.match_score if l.match_score is not None else -1),
                reverse=True,
            )

        render_table(state.results, query, show_match=show_match)
        if not state.results:
            return f"Found 0 listings for '{query}'."
        top = state.results[0]
        return (
            f"Found {len(state.results)} listings for '{query}'. "
            f"Top result: {top.title} @ {top.company}."
        )

    def filter_results(
        job_type: str | None = None,
        location_contains: str | None = None,
        company_contains: str | None = None,
        keyword: str | None = None,
    ) -> str:
        if not state.results:
            return "No results to filter. Run search_jobs first."
        before = len(state.results)
        filtered = state.results
        if job_type:
            jt = job_type.lower()
            filtered = [l for l in filtered if (l.job_type or "").lower() == jt]
        if location_contains:
            lc = location_contains.lower()
            filtered = [l for l in filtered if lc in (l.location or "").lower()]
        if company_contains:
            cc = company_contains.lower()
            filtered = [l for l in filtered if cc in (l.company or "").lower()]
        if keyword:
            kw = keyword.lower()
            filtered = [l for l in filtered if kw in (l.title or "").lower()]

        if not filtered:
            return (
                f"No results match those filters. Current results unchanged ({before})."
            )
        state.results = filtered
        render_table(
            state.results,
            state.last_query or "filtered",
            show_match=any(l.match_score is not None for l in state.results),
        )
        return f"Filtered to {len(state.results)} listings (was {before})."

    def match_resume() -> str:
        if not state.has_resume():
            return (
                "No resume loaded. Use /resume <path> in the REPL to load one, then ask me again."
            )
        if not state.results:
            return "No results to score. Run search_jobs first."
        with state.console.status("[dim]scoring resume…[/dim]"):
            show_match = _score_state_results(state)
        if not show_match:
            return "Scoring failed; no match scores available."
        state.results.sort(
            key=lambda l: (l.match_score if l.match_score is not None else -1),
            reverse=True,
        )
        render_table(state.results, state.last_query or "results", show_match=True)
        scored = [l.match_score for l in state.results if l.match_score is not None]
        if scored:
            scored_sorted = sorted(scored)
            median = scored_sorted[len(scored_sorted) // 2]
            return f"Scored {len(scored)} listings. Median match: {median}%."
        return "Scoring completed but produced no scores."

    def open_job(index: int) -> str:
        if not state.results:
            return "No results loaded."
        if index < 1 or index > len(state.results):
            return f"Result #{index} does not exist (have {len(state.results)})."
        listing = state.results[index - 1]
        if not listing.url:
            return f"Result #{index} has no URL."
        webbrowser.open(listing.url)
        state.console.print(f"Opening [cyan]{listing.url}[/cyan] in browser.")
        return f"Opened {listing.url}"

    def show_requirements(index: int) -> str:
        if not state.results:
            return "No results loaded."
        if index < 1 or index > len(state.results):
            return f"Result #{index} does not exist (have {len(state.results)})."
        listing = state.results[index - 1]
        from langchain_core.messages import HumanMessage, SystemMessage

        sys_prompt = (
            "You infer likely job requirements from limited listing metadata "
            "(title, company, location, type). Output 3-5 short bulleted skill "
            'names prefixed with "• ". End with the line: '
            '"Note: inferred from metadata only; see the URL for the full JD."'
        )
        user_prompt = (
            f"Listing:\nTitle: {listing.title}\nCompany: {listing.company}\n"
            f"Location: {listing.location}\nType: {listing.job_type}"
        )
        try:
            response = state.llm.invoke(
                [SystemMessage(content=sys_prompt), HumanMessage(content=user_prompt)]
            )
        except Exception as exc:
            return f"Could not summarize: {type(exc).__name__}."
        text = getattr(response, "content", str(response))
        if isinstance(text, list):
            text = "".join(
                str(p.get("text", p)) if isinstance(p, dict) else str(p) for p in text
            )
        url_line = f"\nURL: {listing.url}" if listing.url else ""
        return f"{listing.company} — {listing.title}:\n{text}{url_line}"

    def export_csv(path: str) -> str:
        if not state.results:
            return "No results to export."
        expanded = os.path.expanduser(path)
        if os.path.exists(expanded):
            return f"File '{expanded}' already exists. Pick a different path."
        try:
            write_csv(state.results, expanded)
        except OSError as exc:
            return f"Could not write '{expanded}': {exc}."
        return f"Exported {len(state.results)} listings to {expanded}."

    return [
        StructuredTool.from_function(
            func=search_jobs,
            name="search_jobs",
            description=(
                "Search job listings across all sources. Replaces current results "
                "and renders a table. Use when the user asks for new jobs."
            ),
            args_schema=SearchJobsArgs,
        ),
        StructuredTool.from_function(
            func=filter_results,
            name="filter_results",
            description=(
                "Filter the in-memory results by job_type, location substring, "
                "company substring, or title keyword. Mutates current results."
            ),
            args_schema=FilterArgs,
        ),
        StructuredTool.from_function(
            func=match_resume,
            name="match_resume",
            description=(
                "Score current results against the loaded resume and re-sort by match. "
                "No-op message if no resume is loaded."
            ),
            args_schema=MatchArgs,
        ),
        StructuredTool.from_function(
            func=open_job,
            name="open_job",
            description="Open the result at 1-based index in the user's browser.",
            args_schema=OpenJobArgs,
        ),
        StructuredTool.from_function(
            func=show_requirements,
            name="show_requirements",
            description=(
                "Summarize likely required skills for the result at 1-based index, "
                "inferred from metadata."
            ),
            args_schema=ShowReqArgs,
        ),
        StructuredTool.from_function(
            func=export_csv,
            name="export_csv",
            description="Export the current results to a CSV file. Refuses to overwrite.",
            args_schema=ExportArgs,
        ),
    ]


def _score_state_results(state: ChatState) -> bool:
    """Score state.results in place. Returns True when at least one score landed."""
    from ai.scorer import score_listings

    try:
        result = score_listings(state.results, state.resume_text or "", state.llm)
    except Exception:
        return False
    if not result.scores:
        return False
    for idx, listing in enumerate(state.results):
        listing.match_score = result.scores.get(idx)
    return True
