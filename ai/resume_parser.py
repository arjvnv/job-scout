from __future__ import annotations

from pathlib import Path

MAX_RESUME_CHARS: int = 20_000
MAX_PDF_PAGES: int = 50

_TEXT_EXTENSIONS = {"", ".txt", ".md"}


def load_resume(path: str) -> str:
    """Load a resume file and return extracted plain text.

    Supports PDF (via pypdf) and plain text. Raises ValueError on unsupported
    extensions. Returns "" when no text can be extracted (e.g. scanned PDF).
    """
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        raise ValueError(f"Resume file not found: {path}")

    ext = p.suffix.lower()
    if ext == ".pdf":
        text = _read_pdf(p)
    elif ext in _TEXT_EXTENSIONS:
        text = p.read_text(encoding="utf-8", errors="ignore")
    else:
        raise ValueError(
            f"Unsupported resume format: {ext or '(none)'}. "
            "Supported: .pdf, .txt."
        )

    cleaned = text.strip()
    if len(cleaned) > MAX_RESUME_CHARS:
        cleaned = cleaned[:MAX_RESUME_CHARS]
    return cleaned


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = reader.pages[:MAX_PDF_PAGES]
    parts: list[str] = []
    for page in pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)
