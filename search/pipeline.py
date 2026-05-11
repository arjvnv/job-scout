from __future__ import annotations

import concurrent.futures
import re
from typing import Iterable

from rapidfuzz import fuzz
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from models import JobListing
from search.query import (
    filter_by_relevance,
    infer_job_type_from_title,
    infer_level_from_title,
)
from sources.base import JobSource


_COMPANY_LEGAL_SUFFIXES = (
    "incorporated",
    "inc.",
    "inc",
    "llc",
    "ltd.",
    "ltd",
    "corp.",
    "corp",
    "corporation",
    "gmbh",
    "co.",
    "co",
    "plc",
    "s.a.",
    "ag",
)
_COMPANY_PUNCT_RE = re.compile(r"[^\w\s]")
_COMPANY_WS_RE = re.compile(r"\s+")


def fetch_all(
    sources: Iterable[JobSource],
    query: str,
    job_type: str | None,
    location: str | None,
    limit: int,
    console: Console,
) -> list[JobListing]:
    """Concurrently fetch listings from all sources, with a per-source spinner."""
    results: list[JobListing] = []
    sources_list = list(sources)

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        source_tasks = {
            s.name: progress.add_task(f"[dim]Searching {s.name}...[/dim]", total=None)
            for s in sources_list
        }

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, len(sources_list))
        ) as executor:
            future_to_source = {
                executor.submit(s.search, query, job_type, location, limit): s
                for s in sources_list
            }
            for future in concurrent.futures.as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    batch = future.result()
                    results.extend(batch)
                    progress.update(
                        source_tasks[source.name],
                        description=f"[green]✓[/green] {source.name} ({len(batch)} results)",
                        completed=True,
                    )
                except Exception as exc:
                    progress.update(
                        source_tasks[source.name],
                        description=f"[yellow]⚠[/yellow] {source.name} skipped: {type(exc).__name__}",
                        completed=True,
                    )
    return results


def apply_title_based_job_type(listings: list[JobListing]) -> None:
    for listing in listings:
        inferred = infer_job_type_from_title(listing.title)
        if inferred:
            listing.job_type = inferred
        elif not listing.job_type:
            listing.job_type = "full-time"


def apply_level_inference(listings: list[JobListing]) -> None:
    for listing in listings:
        listing.level = infer_level_from_title(listing.title)


def dedupe_by_url(listings: list[JobListing]) -> list[JobListing]:
    seen: set[str] = set()
    unique: list[JobListing] = []
    for listing in listings:
        key = listing.url or f"{listing.source}:{listing.title}:{listing.company}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(listing)
    return unique


def _normalize_company(c: str) -> str:
    if not c:
        return ""
    s = c.lower().strip()
    # Strip a single trailing legal suffix (e.g. "Acme, Inc." -> "acme")
    for suffix in _COMPANY_LEGAL_SUFFIXES:
        if s.endswith(" " + suffix):
            s = s[: -(len(suffix) + 1)].rstrip(" ,")
            break
        if s.endswith("," + suffix) or s.endswith(", " + suffix):
            # already handled above for the spaced form
            pass
    s = _COMPANY_PUNCT_RE.sub(" ", s)
    s = _COMPANY_WS_RE.sub(" ", s).strip()
    return s


def _locations_match(a: str | None, b: str | None) -> bool:
    a_clean = (a or "").strip().lower()
    b_clean = (b or "").strip().lower()
    if not a_clean and not b_clean:
        return True
    if not a_clean or not b_clean:
        return True
    if "remote" in a_clean and "remote" in b_clean:
        return True
    city_a = a_clean.split(",", 1)[0].strip()
    city_b = b_clean.split(",", 1)[0].strip()
    if not city_a or not city_b:
        return True
    return fuzz.ratio(city_a, city_b) > 85


def _is_same_listing(a: JobListing, b: JobListing) -> bool:
    title_sim = fuzz.token_set_ratio(a.title.lower(), b.title.lower())
    if title_sim <= 85:
        return False
    company_sim = fuzz.token_set_ratio(
        _normalize_company(a.company), _normalize_company(b.company)
    )
    if company_sim <= 90:
        return False
    return _locations_match(a.location, b.location)


def _pick_richer(a: JobListing, b: JobListing) -> JobListing:
    a_has_sal = bool(a.salary_range)
    b_has_sal = bool(b.salary_range)
    if a_has_sal and b_has_sal:
        a_date = a.posted_date or ""
        b_date = b.posted_date or ""
        if a_date and b_date:
            return a if a_date[:10] >= b_date[:10] else b
        if a_date != b_date:
            return a if a_date else b
        return a
    if a_has_sal != b_has_sal:
        return a if a_has_sal else b
    a_date = a.posted_date or ""
    b_date = b.posted_date or ""
    if a_date and b_date:
        return a if a_date[:10] >= b_date[:10] else b
    if a_date != b_date:
        return a if a_date else b
    if bool(a.url) != bool(b.url):
        return a if a.url else b
    return a


def dedupe_fuzzy(listings: list[JobListing]) -> list[JobListing]:
    kept: list[JobListing] = []
    for cur in listings:
        match_idx: int | None = None
        for i, prev in enumerate(kept):
            if _is_same_listing(cur, prev):
                match_idx = i
                break
        if match_idx is None:
            kept.append(cur)
        else:
            kept[match_idx] = _pick_richer(kept[match_idx], cur)
    return kept


def sort_key(listing: JobListing) -> tuple[int, str]:
    if listing.posted_date:
        return (1, listing.posted_date)
    return (0, "")


def run_pipeline(
    sources: Iterable[JobSource],
    query: str,
    job_type: str | None,
    location: str | None,
    limit: int,
    console: Console,
) -> list[JobListing]:
    """Full search pipeline: fetch -> filter -> infer types -> filter type -> infer level -> dedupe (url then fuzzy) -> sort."""
    listings = fetch_all(sources, query, job_type, location, limit, console)
    listings = filter_by_relevance(listings, query)
    apply_title_based_job_type(listings)
    if job_type:
        listings = [l for l in listings if l.job_type == job_type]
    apply_level_inference(listings)
    listings = dedupe_by_url(listings)
    listings = dedupe_fuzzy(listings)
    listings.sort(key=sort_key, reverse=True)
    return listings
