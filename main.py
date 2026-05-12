from __future__ import annotations

import os
import sys
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markup import escape

from config import DEFAULT_LIMIT, SOURCE_REGISTRY
from models import JobListing
from output.csv_writer import write_csv
from output.table import render_table
from search.pipeline import run_pipeline
from search.query import expand_query
from sources.base import JobSource


VALID_TYPES = ("full-time", "internship", "research", "contract", "any")
VALID_LEVELS = ("any", "intern", "junior", "mid", "senior", "lead")

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
    type=click.IntRange(1, 500),
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
@click.option(
    "-w",
    "--posted-within",
    "posted_within",
    type=int,
    default=None,
    help="Only show listings posted within the last N days.",
)
@click.option(
    "--level",
    type=click.Choice(VALID_LEVELS, case_sensitive=False),
    default="any",
    show_default=True,
    help="Seniority filter.",
)
@click.option(
    "--browse",
    is_flag=True,
    default=False,
    help="Browse results interactively (arrow keys, Enter to open).",
)
@click.option(
    "--alerts",
    "run_alerts_flag",
    is_flag=True,
    default=False,
    help="Run all saved alerts and exit (no AI key required).",
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
    posted_within: int | None,
    level: str,
    browse: bool,
    run_alerts_flag: bool,
) -> None:
    console = Console()

    if run_alerts_flag:
        conflicts: list[str] = []
        if query:
            conflicts.append("QUERY")
        if chat_mode:
            conflicts.append("--chat")
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
        if resume_path:
            conflicts.append("--resume")
        if posted_within is not None:
            conflicts.append("--posted-within")
        if level and level != "any":
            conflicts.append("--level")
        if browse:
            conflicts.append("--browse")
        if conflicts:
            raise click.UsageError(
                "--alerts is mutually exclusive with: " + ", ".join(conflicts)
            )
        from tracker.alerts import run_all_alerts

        run_all_alerts(console)
        return

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
            posted_within=posted_within,
            level=level,
            browse=browse,
        )
        return

    if not query:
        raise click.UsageError("Missing argument 'QUERY'.")

    if posted_within is not None and posted_within < 1:
        raise click.UsageError("--posted-within must be >= 1")

    expanded, was_expanded = expand_query(query)
    normalized = expanded
    if was_expanded:
        console.print(
            f'[dim]Searching for "{escape(expanded)}" '
            f'(expanded from "{escape(query.strip())}")[/dim]'
        )

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

    if posted_within is not None:
        listings = _apply_posted_within_filter(listings, posted_within, console)

    if level != "any":
        before = len(listings)
        listings = [l for l in listings if l.level == level]
        dropped = before - len(listings)
        if dropped:
            console.print(
                f"[dim]Level filter '{level}': dropped {dropped} non-matching listing(s).[/dim]"
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
                _safe_open_url(url, console)
            else:
                console.print("[yellow]No URL available for that result.[/yellow]")
        else:
            console.print(f"[yellow]Result #{open_index} does not exist (total: {len(listings)}).[/yellow]")

    if export:
        write_csv(listings, export)

    if browse:
        if not listings:
            console.print("[dim]No results to browse.[/dim]")
        else:
            _run_browser(listings, console)


def _safe_open_url(url: str | None, console: Console) -> bool:
    if not url:
        return False
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.netloc:
        console.print("[yellow]Warning:[/yellow] skipping non-http(s) URL.")
        return False
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in url):
        console.print("[yellow]Warning:[/yellow] skipping URL with control characters.")
        return False
    webbrowser.open(url, new=2)
    return True


def _parse_posted_date(s: str | None) -> datetime | None:
    if not s:
        return None
    raw = s.strip()
    if not raw:
        return None
    candidates = [raw]
    if raw.endswith("Z"):
        candidates.append(raw[:-1] + "+00:00")
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        candidates.append(raw[:10])
    for cand in candidates:
        try:
            dt = datetime.fromisoformat(cand)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _apply_posted_within_filter(
    listings: list[JobListing], days: int, console: Console
) -> list[JobListing]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    kept: list[JobListing] = []
    dropped = 0
    unknown_kept = 0
    for listing in listings:
        parsed = _parse_posted_date(listing.posted_date)
        if parsed is None:
            kept.append(listing)
            unknown_kept += 1
            continue
        if parsed >= cutoff:
            kept.append(listing)
        else:
            dropped += 1
    console.print(
        f"[dim]Filtered to listings posted within last {days} days "
        f"(dropped {dropped}, kept {unknown_kept} with unknown dates).[/dim]"
    )
    return kept


def _run_browser(listings: list[JobListing], console: Console) -> None:
    if not sys.stdout.isatty():
        console.print(
            "[yellow]Interactive browser requires a TTY; skipping --browse.[/yellow]"
        )
        return

    if not listings:
        return

    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.formatted_text import FormattedText
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import HSplit, Layout, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.dimension import Dimension
    except ImportError:
        console.print(
            "[yellow]prompt_toolkit not available; skipping --browse.[/yellow]"
        )
        return

    state = {
        "idx": 0,
        "status": None,
        "status_until": 0.0,
        "opened": 0,
    }

    def _title_bar():
        return FormattedText([("bold", "job-scout — browse mode")])

    def _strip_bidi(s: str) -> str:
        from output.table import _BIDI_CODE_POINTS
        return "".join(c for c in s if c not in _BIDI_CODE_POINTS)

    def _truncate(s: str, width: int) -> str:
        if width <= 0:
            return ""
        if len(s) <= width:
            return s
        if width == 1:
            return "…"
        return s[: width - 1] + "…"

    def _pad(s: str, width: int) -> str:
        s = _truncate(s, width)
        return s + " " * (width - len(s))

    def _render_rows():
        try:
            term_width = os.get_terminal_size().columns
        except OSError:
            term_width = 100
        idx_w = 4
        company_w = 24
        location_w = 18
        source_w = 12
        cursor_w = 2
        gap = 4
        used = cursor_w + idx_w + company_w + location_w + source_w + gap
        title_w = max(12, term_width - used)

        rows: list[tuple[str, str]] = []
        for i, listing in enumerate(listings):
            cursor = "> " if i == state["idx"] else "  "
            line = (
                cursor
                + _pad(str(i + 1), idx_w)
                + " "
                + _pad(_strip_bidi(listing.title or ""), title_w)
                + " "
                + _pad(_strip_bidi(listing.company or ""), company_w)
                + " "
                + _pad(_strip_bidi(listing.location or ""), location_w)
                + " "
                + _pad(listing.source or "", source_w)
            )
            style = "bold cyan" if i == state["idx"] else ""
            rows.append((style, line + "\n"))
        return FormattedText(rows)

    def _render_status():
        now = time.monotonic()
        if state["status"] and now < state["status_until"]:
            return FormattedText([("reverse", state["status"])])
        state["status"] = None
        text = (
            f"↑↓/jk navigate   Enter open   q quit   "
            f"({state['idx'] + 1} of {len(listings)})"
        )
        return FormattedText([("reverse", text)])

    def _set_status(msg: str, seconds: float = 1.5) -> None:
        state["status"] = msg
        state["status_until"] = time.monotonic() + seconds

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _(event):
        state["idx"] = max(0, state["idx"] - 1)
        event.app.invalidate()

    @kb.add("down")
    @kb.add("j")
    def _(event):
        state["idx"] = min(max(0, len(listings) - 1), state["idx"] + 1)
        event.app.invalidate()

    @kb.add("g")
    def _(event):
        state["idx"] = 0
        event.app.invalidate()

    @kb.add("G")
    def _(event):
        state["idx"] = max(0, len(listings) - 1)
        event.app.invalidate()

    @kb.add("pageup")
    def _(event):
        state["idx"] = max(0, state["idx"] - 10)
        event.app.invalidate()

    @kb.add("pagedown")
    def _(event):
        state["idx"] = min(max(0, len(listings) - 1), state["idx"] + 10)
        event.app.invalidate()

    @kb.add("enter")
    def _(event):
        url = listings[state["idx"]].url
        if url:
            if _safe_open_url(url, console):
                state["opened"] += 1
            else:
                _set_status("[URL rejected]")
        else:
            _set_status("[no URL for this result]")
        event.app.invalidate()

    @kb.add("q")
    @kb.add("c-c")
    def _(event):
        event.app.exit()

    app = Application(
        layout=Layout(
            HSplit(
                [
                    Window(FormattedTextControl(_title_bar), height=1),
                    Window(
                        FormattedTextControl(_render_rows, focusable=True),
                        height=Dimension(min=1),
                        wrap_lines=False,
                    ),
                    Window(FormattedTextControl(_render_status), height=1),
                ]
            )
        ),
        key_bindings=kb,
        full_screen=True,
    )

    try:
        app.run()
    except Exception as exc:
        console.print(
            f"[yellow]Browser exited unexpectedly ({type(exc).__name__}); continuing.[/yellow]"
        )
        return

    if state["opened"]:
        console.print(
            f"Closed browser. {state['opened']} result(s) opened."
        )


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
    posted_within: int | None,
    level: str,
    browse: bool,
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
    if posted_within is not None:
        conflicts.append("--posted-within")
    if level and level != "any":
        conflicts.append("--level")
    if browse:
        conflicts.append("--browse")
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
