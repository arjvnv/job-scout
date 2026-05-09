from __future__ import annotations

import os
import sys
import webbrowser

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape

from config import DEFAULT_LIMIT, SOURCE_REGISTRY
from models import JobListing
from output.csv_writer import write_csv
from output.table import render_table
from search.pipeline import run_pipeline
from search.query import normalize_query
from sources.base import JobSource


VALID_TYPES = ("full-time", "internship", "research", "contract", "any")

_AI_PROVIDER_CHOICES: list[tuple[str, str, str]] = [
    ("OpenAI", "OPENAI_API_KEY", "OpenAI API Key"),
    ("Anthropic", "ANTHROPIC_API_KEY", "Anthropic API Key"),
    ("Gemini", "GEMINI_API_KEY", "Gemini API Key"),
]


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("query", required=False)
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
@click.option(
    "--resume",
    "resume_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Score results against a resume (PDF or text).",
)
@click.option(
    "--chat",
    "chat_mode",
    is_flag=True,
    default=False,
    help="Launch interactive AI chat REPL.",
)
def cli(
    query: str | None,
    job_type: str,
    location: str | None,
    limit: int,
    export: str | None,
    sources_arg: str | None,
    force: bool,
    open_index: int | None,
    resume_path: str | None,
    chat_mode: bool,
) -> None:
    console = Console()
    _maybe_run_setup(console)

    if chat_mode:
        _run_chat_mode(
            console=console,
            query=query,
            job_type=job_type,
            location=location,
            limit=limit,
            export=export,
            sources_arg=sources_arg,
            force=force,
            open_index=open_index,
            resume_path=resume_path,
        )
        return

    if not query:
        raise click.UsageError("Missing argument 'QUERY'.")

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

    listings = run_pipeline(
        selected, normalized, effective_type, location, limit, console
    )

    scoring_result = None
    show_match = False
    if resume_path:
        scoring_result, show_match = _maybe_score_listings(
            listings, resume_path, console
        )
        if show_match:
            listings.sort(
                key=lambda l: (l.match_score if l.match_score is not None else -1),
                reverse=True,
            )

    render_table(listings, query, show_match=show_match)

    if scoring_result is not None and show_match:
        _render_scoring_extras(scoring_result, console)

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


def _run_chat_mode(
    console: Console,
    query: str | None,
    job_type: str,
    location: str | None,
    limit: int,
    export: str | None,
    sources_arg: str | None,
    force: bool,
    open_index: int | None,
    resume_path: str | None,
) -> None:
    conflicts: list[str] = []
    if query:
        conflicts.append("QUERY")
    if job_type and job_type != "any":
        conflicts.append("--type")
    if location:
        conflicts.append("--location")
    if limit != DEFAULT_LIMIT:
        conflicts.append("--limit")
    if export:
        conflicts.append("--export")
    if sources_arg:
        conflicts.append("--sources")
    if force:
        conflicts.append("--force")
    if open_index is not None:
        conflicts.append("--open")
    if conflicts:
        raise click.UsageError(
            "--chat is mutually exclusive with: " + ", ".join(conflicts)
        )

    _require_ai_or_exit(console)

    effective_resume = resume_path or os.getenv("RESUME_PATH")
    if effective_resume and not os.path.isfile(os.path.expanduser(effective_resume)):
        console.print(
            f"[yellow]Warning:[/yellow] resume path '{effective_resume}' not found; "
            "starting chat without a resume."
        )
        effective_resume = None

    from ai.agent import run_chat

    run_chat(effective_resume)


def _maybe_score_listings(
    listings: list[JobListing],
    resume_path: str,
    console: Console,
):
    from ai.provider import build_llm
    from ai.resume_parser import load_resume
    from ai.scorer import score_listings

    llm = build_llm()
    if llm is None:
        console.print(
            "[yellow]Resume scoring requires an AI key (OPENAI_API_KEY, "
            "ANTHROPIC_API_KEY, or GEMINI_API_KEY). Skipping.[/yellow]"
        )
        return None, False

    try:
        resume_text = load_resume(resume_path)
    except ValueError as exc:
        console.print(f"[yellow]Resume could not be loaded: {escape(str(exc))}. Skipping scoring.[/yellow]")
        return None, False

    if not resume_text.strip():
        console.print(
            "[yellow]Resume appears empty (no extractable text); skipping scoring.[/yellow]"
        )
        return None, False

    if not listings:
        return None, False

    console.print(f"[dim]Scoring {len(listings)} listings against resume...[/dim]")
    try:
        result = score_listings(listings, resume_text, llm)
    except Exception as exc:
        console.print(f"[yellow]Scoring failed: {escape(type(exc).__name__)}. Continuing without scores.[/yellow]")
        return None, False

    for idx, listing in enumerate(listings):
        listing.match_score = result.scores.get(idx)

    if result.failed_batches and result.total_batches:
        scored = sum(1 for l in listings if l.match_score is not None)
        console.print(
            f"[yellow]Scoring partially failed — {scored} of {len(listings)} listings scored.[/yellow]"
        )

    return result, True


def _render_scoring_extras(result, console: Console) -> None:
    if result.skills_gap:
        console.print("\n[bold]Skills Gap[/bold] (frequent in listings, missing from resume):")
        for skill, count in result.skills_gap:
            console.print(f"  • {escape(skill)} (in {count} listing{'s' if count != 1 else ''})")
    if result.tips:
        console.print("\n[bold]Resume Tips[/bold]:")
        for tip in result.tips:
            console.print(f"  • {escape(tip)}")


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


def _render_links(listings: list[JobListing], console: Console) -> None:
    if not listings:
        return
    console.print("\n[bold]Application Links[/bold]")
    for i, listing in enumerate(listings, start=1):
        if listing.url:
            console.print(f"  [dim]{i:>3}[/dim]  {listing.url}")


def _require_ai_or_exit(console: Console) -> None:
    from ai.provider import detect_provider

    if detect_provider() is None:
        console.print(
            "Chat mode requires an AI provider key (OpenAI, Anthropic, or Gemini)."
        )
        console.print(
            "Add one of OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY to .env, then re-run."
        )
        sys.exit(1)


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

    _prompt_ai_setup(console, lines)

    with open(".env", "w") as f:
        f.write("\n".join(lines) + "\n" if lines else "")

    load_dotenv(override=True)
    console.print("\n[green]Setup complete.[/green] Starting search...\n")


def _prompt_ai_setup(console: Console, lines: list[str]) -> None:
    console.print(
        "\n[bold]Optional: enable AI features[/bold] (chat mode and resume matching)."
    )
    console.print("  Choose a provider:")
    console.print("    1) OpenAI       (env: OPENAI_API_KEY)")
    console.print("    2) Anthropic    (env: ANTHROPIC_API_KEY)")
    console.print("    3) Gemini       (env: GEMINI_API_KEY)")
    console.print("    4) Skip")
    choice = click.prompt(
        "Choice",
        type=click.Choice(["1", "2", "3", "4"]),
        default="4",
        show_choices=False,
    )
    if choice in {"1", "2", "3"}:
        _, env_var, label = _AI_PROVIDER_CHOICES[int(choice) - 1]
        key = click.prompt(f"{label} (input hidden)", hide_input=True, default="", show_default=False)
        if key:
            lines.append(f"{env_var}={key}")

    resume_path = click.prompt(
        "Default resume path (optional, press Enter to skip)",
        default="",
        show_default=False,
    )
    if resume_path:
        expanded = os.path.expanduser(resume_path)
        if os.path.isfile(expanded):
            lines.append(f"RESUME_PATH={expanded}")
        else:
            console.print(
                f"[yellow]Resume path '{escape(resume_path)}' not found; not saved.[/yellow]"
            )


if __name__ == "__main__":
    cli()
