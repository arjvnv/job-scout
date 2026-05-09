from __future__ import annotations

import csv
from dataclasses import asdict, fields

from rich.console import Console
from rich.markup import escape

from models import JobListing


# Leading characters that, when interpreted by Excel/Sheets, can trigger
# formula evaluation (CSV injection). Tab/CR are also abused for cell-bleed.
_CSV_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(v: str | None) -> str:
    if v is None:
        return ""
    if v.startswith(_CSV_DANGEROUS_PREFIXES):
        return "'" + v
    return v


def write_csv(listings: list[JobListing], path: str) -> None:
    fieldnames = [f.name for f in fields(JobListing)]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for listing in listings:
            row = asdict(listing)
            sanitized = {
                k: _csv_safe(v) if isinstance(v, str) or v is None else v
                for k, v in row.items()
            }
            writer.writerow(sanitized)

    Console().print(
        f"[green]Exported[/green] {len(listings)} listing(s) to "
        f"[bold]{escape(path)}[/bold]"
    )
