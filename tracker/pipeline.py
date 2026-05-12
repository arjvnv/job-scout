from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

DATA_DIR: Path = Path.home() / ".job-scout"
PIPELINE_PATH: Path = DATA_DIR / "pipeline.json"

# Refuse to load files larger than this — defends against accidental bloat
# or a tampered-with file being slurped into memory.
_MAX_FILE_BYTES: int = 5 * 1024 * 1024  # 5 MB
# Per-field cap when coercing untrusted entries on load.
_MAX_FIELD_BYTES: int = 2 * 1024  # 2 KB

VALID_STATUSES: tuple[str, ...] = (
    "interested",
    "applied",
    "phone_screen",
    "interviewing",
    "offer",
    "rejected",
)

# Canonical render order for show_pipeline grouping.
STATUS_ORDER: tuple[str, ...] = (
    "applied",
    "phone_screen",
    "interviewing",
    "offer",
    "interested",
    "rejected",
)


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
        # Slice on character count first as a fast guard, then re-check bytes.
        s = s[:_MAX_FIELD_BYTES]
        encoded = s.encode("utf-8", errors="ignore")[:_MAX_FIELD_BYTES]
        s = encoded.decode("utf-8", errors="ignore")
    return s


def _sanitize_entry(entry: dict) -> dict:
    """Coerce known-string fields to bounded strings; pass others through."""
    sanitized = dict(entry)
    for key in ("title", "company", "url", "status"):
        if key in sanitized:
            sanitized[key] = _coerce_field(sanitized[key])
    return sanitized


def load_pipeline() -> list[dict]:
    """Load pipeline entries. Returns [] on missing or malformed file."""
    try:
        if PIPELINE_PATH.stat().st_size > _MAX_FILE_BYTES:
            _warn_corrupt(PIPELINE_PATH)
            return []
        raw = PIPELINE_PATH.read_text()
    except FileNotFoundError:
        return []
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        _warn_corrupt(PIPELINE_PATH)
        return []
    if not isinstance(data, list):
        _warn_corrupt(PIPELINE_PATH)
        return []
    # Defensive: drop any non-dict entries and coerce key string fields.
    return [_sanitize_entry(e) for e in data if isinstance(e, dict)]


def _ensure_data_dir() -> None:
    """Create DATA_DIR with restrictive perms and refuse to write to a symlink."""
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    # If a pre-existing directory has looser perms, tighten them.
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
    # Refuse to follow a symlinked data dir — that would let an attacker
    # redirect our writes outside the home dir.
    if DATA_DIR.is_symlink():
        raise RuntimeError(f"Refusing to write: {DATA_DIR} is a symlink.")


def save_pipeline(entries: list[dict]) -> None:
    """Atomic write of the full pipeline list. Creates ~/.job-scout/ lazily."""
    _ensure_data_dir()
    fd, tmp_path = tempfile.mkstemp(
        dir=str(DATA_DIR), prefix="pipeline.", suffix=".json.tmp"
    )
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            # Best-effort on platforms without fchmod support for the descriptor.
            pass
        with os.fdopen(fd, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp_path, PIPELINE_PATH)
    except Exception:
        # Clean up the temp file on any failure between create and replace.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def upsert(entry: dict) -> dict:
    """Insert or update by URL. Always refreshes date_tracked.

    Returns the stored entry (with date_tracked populated).
    Raises ValueError if entry has no URL.
    """
    url = (entry.get("url") or "").strip()
    if not url:
        raise ValueError("Pipeline entry requires a non-empty URL.")
    entries = load_pipeline()
    entry = dict(entry)  # avoid mutating caller's dict
    entry["url"] = url
    entry.setdefault("status", "interested")
    entry["date_tracked"] = _now_iso()
    replaced = False
    for i, existing in enumerate(entries):
        if (existing.get("url") or "") == url:
            entries[i] = entry
            replaced = True
            break
    if not replaced:
        entries.append(entry)
    save_pipeline(entries)
    return entry


def remove_by_url(url: str) -> bool:
    """Remove an entry by URL. Returns True if anything was removed."""
    if not url:
        return False
    entries = load_pipeline()
    new_entries = [e for e in entries if (e.get("url") or "") != url]
    if len(new_entries) == len(entries):
        return False
    save_pipeline(new_entries)
    return True


def find_matches(identifier: str, entries: list[dict]) -> list[int]:
    """Resolve a user-supplied identifier to pipeline entry indices.

    Identifier may be:
      - A 1-based index string ("1", "2", ...) -> that single entry if in range.
      - Otherwise, case-insensitive substring match against company or title.

    Returns a list of 0-based indices into `entries`.
    """
    ident = (identifier or "").strip()
    if not ident:
        return []
    # Numeric path
    if ident.isdigit():
        idx = int(ident) - 1
        if 0 <= idx < len(entries):
            return [idx]
        return []
    needle = ident.lower()
    matches: list[int] = []
    for i, e in enumerate(entries):
        company = (e.get("company") or "").lower()
        title = (e.get("title") or "").lower()
        if needle in company or needle in title:
            matches.append(i)
    return matches


def status_by_url(entries: list[dict] | None = None) -> dict[str, str]:
    """Return a {url: status} map. Loads from disk when entries is None."""
    if entries is None:
        entries = load_pipeline()
    out: dict[str, str] = {}
    for e in entries:
        url = (e.get("url") or "").strip()
        status = e.get("status") or ""
        # Only surface whitelisted statuses — guards downstream rendering
        # from styling/markup injection via a tampered pipeline.json.
        if url and status in VALID_STATUSES:
            out[url] = status
    return out


if __name__ == "__main__":
    # Tiny smoke check: round-trip one entry.
    sample = {
        "title": "Senior ML Engineer",
        "company": "Stripe",
        "url": "https://example.test/stripe/123",
        "source": "jobspy",
        "location": "Remote (US)",
        "job_type": "full-time",
        "status": "applied",
    }
    upsert(sample)
    print("loaded:", load_pipeline())
    remove_by_url(sample["url"])
    print("after remove:", load_pipeline())
