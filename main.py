from __future__ import annotations

import concurrent.futures
import os
from typing import Iterable

import click
from rich.console import Console
from rich.markup import escape

from config import DEFAULT_LIMIT, SOURCE_REGISTRY
from models import JobListing
from output.csv_writer import write_csv
from output.table import render_table
from search.query import filter_by_relevance, normalize_query
from sources.base import JobSource


VALID_TYPES = ("full-time", "internship", "research", "contract", "any")


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("query")
@click.option(
    "-t",
    "--type",
    "job_type",
    type=click.Choice(VALID_TYPES, case_sensitive=False),
    default="any",
    show_default=True,
    help="Job type filter.",
)
@click.option(
    "-l",
    "--location",
    default=None,
    help="Location or 'remote'.",
)
@click.option(
    "-n",
    "--limit",
    type=int,
    default=DEFAULT_LIMIT,
    show_default=True,
    help="Max results per source.",
)
@click.option(
    "-e",
    "--export",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Export results to CSV.",
)
@click.option(
    "-s",
    "--sources",
    "sources_arg",
    default=None,
    help="Comma-separated source names to use (e.g. remotive,remoteok).",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite the export file if it already exists.",
)
def cli(
    query: str,
    job_type: str,
    location: str | None,
    limit: int,
    export: str | None,
    sources_arg: str | None,
    force: bool,
) -> None:
    console = Console()
    normalized = normalize_query(query)

    if export:
        if os.path.exists(export) and not force:
            raise click.ClickException(
                f"File '{export}' already exists. Use --force to overwrite."
            )
        if not export.lower().endswith(".csv"):
            console.print(
                "[yellow]Warning:[/yellow] export path does not end with '.csv'."
            )

    selected = _select_sources(SOURCE_REGISTRY, sources_arg, console)
    if not selected:
        console.print("[red]No sources available to query.[/red]")
        return

    effective_type = None if job_type == "any" else job_type

    listings = _fetch_all(
        selected, normalized, effective_type, location, limit, console
    )

    listings = filter_by_relevance(listings, normalized)
    listings = _dedupe_by_url(listings)
    listings.sort(key=_sort_key, reverse=True)

    render_table(listings, query)

    if export:
        write_csv(listings, export)


def _select_sources(
    registry: list[JobSource], sources_arg: str | None, console: Console
) -> list[JobSource]:
    if not sources_arg:
        return registry

    requested = {s.strip().lower() for s in sources_arg.split(",") if s.strip()}
    chosen = [s for s in registry if s.name.lower() in requested]
    missing = requested - {s.name.lower() for s in registry}
    for name in missing:
        console.print(
            f"[yellow]Warning:[/yellow] source '{escape(name)}' not available, skipping."
        )
    return chosen


def _fetch_all(
    sources: Iterable[JobSource],
    query: str,
    job_type: str | None,
    location: str | None,
    limit: int,
    console: Console,
) -> list[JobListing]:
    results: list[JobListing] = []
    sources_list = list(sources)
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
                results.extend(future.result())
            except Exception as exc:
                # Use type(exc).__name__ instead of str(exc) — exception messages
                # from requests.HTTPError can include the full URL with API
                # keys/secrets baked into query parameters.
                console.print(
                    f"[yellow]Warning:[/yellow] {escape(source.name)} failed: "
                    f"{type(exc).__name__}"
                )
    return results


def _dedupe_by_url(listings: list[JobListing]) -> list[JobListing]:
    seen: set[str] = set()
    unique: list[JobListing] = []
    for listing in listings:
        key = listing.url or f"{listing.source}:{listing.title}:{listing.company}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(listing)
    return unique


def _sort_key(listing: JobListing) -> tuple[int, str]:
    # Tuple ordering: entries with a posted_date sort ahead of None entries,
    # and within the dated group the ISO-like strings sort naturally.
    if listing.posted_date:
        return (1, listing.posted_date)
    return (0, "")


if __name__ == "__main__":
    cli()
