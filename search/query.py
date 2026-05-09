from __future__ import annotations

from models import JobListing


def normalize_query(query: str) -> str:
    return query.strip().lower()


def filter_by_relevance(
    listings: list[JobListing], query: str
) -> list[JobListing]:
    normalized = normalize_query(query)
    words = [w for w in normalized.split() if len(w) >= 3]
    if not words:
        return listings

    return [
        listing
        for listing in listings
        if any(word in listing.title.lower() for word in words)
    ]


def infer_job_type_from_title(title: str) -> str | None:
    """Return 'internship' if the title clearly signals an intern role, else None."""
    lower = title.lower()
    if "intern" in lower:
        return "internship"
    return None
