from __future__ import annotations

import unicodedata

from rich.console import Console
from rich.table import Table
from rich.text import Text

from models import JobListing


_TYPE_COLORS: dict[str, str] = {
    "full-time": "green",
    "full_time": "green",
    "internship": "yellow",
    "research": "cyan",
    "contract": "magenta",
}

# BiDi override / isolate / embedding code points that can be used to
# spoof rendered text (RLO/LRO/PDF, isolates, marks).
_BIDI_CODE_POINTS = frozenset(
    {
        "‪",  # LRE
        "‫",  # RLE
        "‬",  # PDF
        "‭",  # LRO
        "‮",  # RLO
        "⁦",  # LRI
        "⁧",  # RLI
        "⁨",  # FSI
        "⁩",  # PDI
        "‎",  # LRM
        "‏",  # RLM
    }
)


def _format_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    # Strip time/timezone from ISO 8601 strings like "2026-05-06T00:01:45+00:00"
    return date_str[:10]


def _safe_cell(s: str | None) -> Text:
    if s is None:
        return Text("")
    cleaned_chars: list[str] = []
    for ch in s:
        if ch in _BIDI_CODE_POINTS:
            continue
        # Strip C0 (except common whitespace) and C1 control characters.
        if unicodedata.category(ch) == "Cc" and ch not in ("\t", "\n"):
            continue
        cleaned_chars.append(ch)
    return Text("".join(cleaned_chars))


def render_table(listings: list[JobListing], query: str) -> None:
    console = Console()
    table = Table(
        title=f'job-scout results for "{query}"',
        show_lines=False,
        header_style="bold",
    )
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("Title", overflow="fold")
    table.add_column("Company")
    table.add_column("Location")
    table.add_column("Type")
    table.add_column("Source")
    table.add_column("Posted")
    table.add_column("Salary")

    for idx, listing in enumerate(listings, start=1):
        type_key = (listing.job_type or "").lower()
        color = _TYPE_COLORS.get(type_key)
        type_display: Text | str
        if color and listing.job_type:
            # job_type is whitelisted via _TYPE_COLORS lookup; safe to style.
            type_display = f"[{color}]{listing.job_type}[/{color}]"
        else:
            type_display = _safe_cell(listing.job_type)

        table.add_row(
            _safe_cell(str(idx)),
            _safe_cell(listing.title),
            _safe_cell(listing.company),
            _safe_cell(listing.location),
            type_display,
            _safe_cell(listing.source),
            _safe_cell(_format_date(listing.posted_date)),
            _safe_cell(listing.salary_range),
        )

    console.print(table)
    console.print(f"[bold]Total:[/bold] {len(listings)} listing(s)")
