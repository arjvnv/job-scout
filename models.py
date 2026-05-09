from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JobListing:
    title: str
    company: str
    location: str
    job_type: str
    url: str
    source: str
    posted_date: str | None = None
    salary_range: str | None = None
