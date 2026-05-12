from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from models import JobListing

DATA_DIR: Path = Path.home() / ".job-scout"
ALERTS_PATH: Path = DATA_DIR / "alerts.json"
SEEN_URL_CAP: int = 5000

# Refuse to slurp absurd files into memory.
_MAX_FILE_BYTES: int = 5 * 1024 * 1024  # 5 MB
_MAX_FIELD_BYTES: int = 2 * 1024  # 2 KB

# Bounds for user-supplied alert parameters.
_LIMIT_MIN: int = 1
_LIMIT_MAX: int = 500
_QUERY_MAX_LEN: int = 500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _warn_corrupt(path: Path) -> None:
    Console().print(
        f"[yellow]Warning:[/yellow] {path} is not valid JSON; treating as empty."
    )


def _coerce_field(value: object) -> str:
    """Coerce an untrusted field to a string and clamp its size."""
    s = "" if value is None else str(value)
    if len(s.encode("utf-8", errors="ignore")) > _MAX_FIELD_BYTES:
        s = s[:_MAX_FIELD_BYTES]
        encoded = s.encode("utf-8", errors="ignore")[:_MAX_FIELD_BYTES]
        s = encoded.decode("utf-8", errors="ignore")
    return s


def _sanitize_alert(entry: dict) -> dict:
    """Coerce known-string fields on a loaded alert to bounded strings."""
    sanitized = dict(entry)
    for key in ("title", "company", "url", "status"):
        if key in sanitized:
            sanitized[key] = _coerce_field(sanitized[key])
    return sanitized


def load_alerts() -> list[dict]:
    try:
        if ALERTS_PATH.stat().st_size > _MAX_FILE_BYTES:
            _warn_corrupt(ALERTS_PATH)
            return []
        raw = ALERTS_PATH.read_text()
    except FileNotFoundError:
        return []
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _warn_corrupt(ALERTS_PATH)
        return []
    if not isinstance(data, list):
        _warn_corrupt(ALERTS_PATH)
        return []
    return [_sanitize_alert(e) for e in data if isinstance(e, dict)]


def _ensure_data_dir() -> None:
    """Create DATA_DIR with restrictive perms and refuse to write to a symlink."""
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
    if DATA_DIR.is_symlink():
        raise RuntimeError(f"Refusing to write: {DATA_DIR} is a symlink.")


def save_alerts(alerts: list[dict]) -> None:
    _ensure_data_dir()
    fd, tmp_path = tempfile.mkstemp(
        dir=str(DATA_DIR), prefix="alerts.", suffix=".json.tmp"
    )
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w") as f:
            json.dump(alerts, f, indent=2)
        os.replace(tmp_path, ALERTS_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Lowercase, kebab-case, ASCII-only slug. Empty input -> 'alert'."""
    s = (text or "").lower().strip()
    s = _SLUG_RE.sub("-", s).strip("-")
    return s or "alert"


def unique_name(base: str, existing_names: set[str]) -> str:
    """Return a name not present in existing_names. Appends -2, -3, ... on collision."""
    if base not in existing_names:
        return base
    i = 2
    while f"{base}-{i}" in existing_names:
        i += 1
    return f"{base}-{i}"


def upsert_alert(alert: dict) -> tuple[dict, bool]:
    """Insert or update an alert by name. Preserves seen_urls + created_at on update.

    Returns (stored_alert, was_update).
    """
    name = (alert.get("name") or "").strip()
    if not name:
        raise ValueError("Alert requires a name.")
    # Validate query length when present. An empty string is allowed only
    # when the alert is being updated without touching the query field.
    if "query" in alert:
        q = alert.get("query")
        if not isinstance(q, str) or not q.strip():
            raise ValueError("Alert query must be a non-empty string.")
        if len(q) > _QUERY_MAX_LEN:
            raise ValueError(
                f"Alert query exceeds {_QUERY_MAX_LEN} characters."
            )
    alerts = load_alerts()
    for i, existing in enumerate(alerts):
        if (existing.get("name") or "") == name:
            merged = dict(existing)
            # Update query/filters but preserve seen_urls + created_at.
            for k in ("query", "job_type", "location", "limit", "sources"):
                if k in alert:
                    merged[k] = alert[k]
            merged["last_run"] = alert.get("last_run") or merged.get("last_run") or _now_iso()
            alerts[i] = merged
            save_alerts(alerts)
            return merged, True
    # New alert.
    new = dict(alert)
    new.setdefault("created_at", _now_iso())
    new.setdefault("last_run", new["created_at"])
    new.setdefault("seen_urls", [])
    alerts.append(new)
    save_alerts(alerts)
    return new, False


def delete_alert(name: str) -> bool:
    if not name:
        return False
    alerts = load_alerts()
    new_alerts = [a for a in alerts if (a.get("name") or "") != name]
    if len(new_alerts) == len(alerts):
        return False
    save_alerts(new_alerts)
    return True


def _trim_seen(seen: list[str], cap: int = SEEN_URL_CAP) -> list[str]:
    if len(seen) <= cap:
        return seen
    # Drop oldest (front) to retain recency at the tail.
    return seen[-cap:]


def _select_sources_for_alert(alert: dict) -> list[Any]:
    from config import SOURCE_REGISTRY

    requested = alert.get("sources")
    if not requested:
        return SOURCE_REGISTRY
    wanted = {s.lower() for s in requested if isinstance(s, str)}
    return [s for s in SOURCE_REGISTRY if s.name.lower() in wanted]


def run_all_alerts(console: Console) -> list[tuple[dict, list[JobListing]]]:
    """Run every saved alert. For each, search, diff against seen_urls, render, persist.

    Returns the list of (alert, new_listings) tuples. Side effect: prints headers + tables.
    """
    from output.table import render_table
    from search.pipeline import run_pipeline
    from search.query import normalize_query

    alerts = load_alerts()
    if not alerts:
        console.print("No alerts saved.")
        return []

    results: list[tuple[dict, list[JobListing]]] = []
    for alert in alerts:
        name = alert.get("name") or "(unnamed)"
        query = alert.get("query") or ""
        job_type = alert.get("job_type") or "any"
        location = alert.get("location")
        try:
            limit = int(alert.get("limit") or 50)
        except (TypeError, ValueError):
            limit = 50
        # Clamp to a sane range — a tampered alerts.json could otherwise
        # request unbounded work from each source.
        limit = max(_LIMIT_MIN, min(_LIMIT_MAX, limit))
        last_run = alert.get("last_run") or alert.get("created_at") or ""
        last_run_short = last_run[:10] if last_run else "never"

        effective_type = None if job_type == "any" else job_type
        sources = _select_sources_for_alert(alert)
        if not sources:
            console.print(
                f"[yellow]{name}: no matching sources available; skipping.[/yellow]"
            )
            continue

        normalized = normalize_query(query)
        try:
            with console.status(f"[dim]running alert '{name}'…[/dim]"):
                listings = run_pipeline(
                    sources, normalized, effective_type, location, limit, console
                )
        except Exception as exc:
            console.print(
                f"[yellow]{name}: search failed ({type(exc).__name__}); skipping.[/yellow]"
            )
            continue

        seen = list(alert.get("seen_urls") or [])
        seen_set = set(seen)
        new_listings = [l for l in listings if l.url and l.url not in seen_set]

        location_label = f" ({location})" if location else ""
        if not new_listings:
            console.print(
                f"{name}: no new listings since {last_run_short}."
            )
        else:
            console.print(
                f"{name}: {len(new_listings)} new listing(s) since {last_run_short}"
            )
            render_table(
                new_listings,
                f"{query}{location_label}".strip() or name,
            )

        # Merge new URLs into seen, FIFO-trim, persist.
        for l in listings:
            if l.url and l.url not in seen_set:
                seen.append(l.url)
                seen_set.add(l.url)
        alert["seen_urls"] = _trim_seen(seen)
        alert["last_run"] = _now_iso()
        results.append((alert, new_listings))

    # Persist all in-place mutations.
    save_alerts(alerts)
    return results
