from __future__ import annotations

import concurrent.futures
from typing import Iterable

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from models import JobListing
from search.query import filter_by_relevance, infer_job_type_from_title
from sources.base import JobSource


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
    """Full search pipeline: fetch -> filter -> infer types -> filter type -> dedupe -> sort."""
    listings = fetch_all(sources, query, job_type, location, limit, console)
    listings = filter_by_relevance(listings, query)
    apply_title_based_job_type(listings)
    if job_type:
        listings = [l for l in listings if l.job_type == job_type]
    listings = dedupe_by_url(listings)
    listings.sort(key=sort_key, reverse=True)
    return listings
