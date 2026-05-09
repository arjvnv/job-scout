from __future__ import annotations

import concurrent.futures
import os
import webbrowser
from typing import Iterable

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn

from config import DEFAULT_LIMIT, SOURCE_REGISTRY
from models import JobListing
from output.csv_writer import write_csv
from output.table import render_table
from search.query import filter_by_relevance, infer_job_type_from_title, normalize_query
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
@click.option(
    "--open",
    "open_index",
    type=int,
    default=None,
    help="Open result #N directly in your browser.",
)
def cli(
    query: str,
    job_type: str,
    location: str | None,
    limit: int,
    export: str | None,
    sources_arg: str | None,
    force: bool,
    open_index: int | None,
) -> None:
    console = Console()
    _maybe_run_setup(console)
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
    _apply_title_based_job_type(listings)
    if effective_type:
        listings = [l for l in listings if l.job_type == effective_type]
    listings = _dedupe_by_url(listings)
    listings.sort(key=_sort_key, reverse=True)

    render_table(listings, query)

    _render_links(listings, console)

    if open_index is not None:
        if 1 <= open_index <= len(listings):
            url = listings[open_index - 1].url
            if url:
                console.print(f"\nOpening [cyan]{url}[/cyan] in browser...")
                webbrowser.open(url)
            else:
                console.print("[yellow]No URL available for that result.[/yellow]")
        else:
            console.print(f"[yellow]Result #{open_index} does not exist (total: {len(listings)}).[/yellow]")

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


def _apply_title_based_job_type(listings: list[JobListing]) -> None:
    """Override job_type in-place when the title makes the type unambiguous."""
    for listing in listings:
        inferred = infer_job_type_from_title(listing.title)
        if inferred:
            listing.job_type = inferred


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


def _render_links(listings: list[JobListing], console: Console) -> None:
    if not listings:
        return
    console.print("\n[bold]Application Links[/bold]")
    for i, listing in enumerate(listings, start=1):
        if listing.url:
            console.print(f"  [dim]{i:>3}[/dim]  {listing.url}")


def _maybe_run_setup(console: Console) -> None:
    """Run a one-time interactive setup if no .env file is present."""
    if os.path.exists(".env"):
        return

    console.print("\n[bold cyan]Welcome to job-scout![/bold cyan]")
    console.print(
        "The tool works out of the box using LinkedIn, Indeed, Glassdoor, "
        "ZipRecruiter, Remotive, RemoteOK, and We Work Remotely — [green]no API keys needed[/green].\n"
    )
    console.print(
        "Optional: you can add free API keys for [bold]Adzuna[/bold] (broader coverage) "
        "and [bold]USAJobs[/bold] (government + research roles)."
    )

    setup = click.confirm("\nWould you like to set up optional API keys now?", default=False)

    lines: list[str] = []

    if setup:
        console.print("\n[dim]Press Enter to skip any key.[/dim]\n")

        adzuna_id = click.prompt("Adzuna App ID", default="", show_default=False)
        adzuna_key = click.prompt("Adzuna App Key", default="", show_default=False)
        if adzuna_id:
            lines.append(f"ADZUNA_APP_ID={adzuna_id}")
        if adzuna_key:
            lines.append(f"ADZUNA_APP_KEY={adzuna_key}")

        usajobs_email = click.prompt("USAJobs User-Agent (your email)", default="", show_default=False)
        usajobs_key = click.prompt("USAJobs Auth Key", default="", show_default=False)
        if usajobs_email:
            lines.append(f"USAJOBS_USER_AGENT={usajobs_email}")
        if usajobs_key:
            lines.append(f"USAJOBS_AUTH_KEY={usajobs_key}")

    with open(".env", "w") as f:
        f.write("\n".join(lines) + "\n" if lines else "")

    load_dotenv(override=True)
    console.print("\n[green]Setup complete.[/green] Starting search...\n")


def _sort_key(listing: JobListing) -> tuple[int, str]:
    # Tuple ordering: entries with a posted_date sort ahead of None entries,
    # and within the dated group the ISO-like strings sort naturally.
    if listing.posted_date:
        return (1, listing.posted_date)
    return (0, "")


if __name__ == "__main__":
    cli()
