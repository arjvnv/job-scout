from __future__ import annotations

import pandas as pd
from jobspy import scrape_jobs

from models import JobListing
from sources.base import JobSource


_JOB_TYPE_MAP: dict[str, str | None] = {
    "full-time": "fulltime",
    "internship": "internship",
    "contract": "contract",
    "part-time": "parttime",
    "research": None,  # no direct mapping; handled by title-based inference in main.py
}

_REVERSE_TYPE_MAP: dict[str, str] = {
    "fulltime": "full-time",
    "parttime": "part-time",
    "internship": "internship",
    "contract": "contract",
}

_SITES = ["linkedin", "indeed", "glassdoor", "zip_recruiter"]


class JobSpySource(JobSource):
    name = "JobSpy"

    def search(
        self,
        query: str,
        job_type: str | None,
        location: str | None,
        limit: int,
    ) -> list[JobListing]:
        is_remote = bool(location and location.lower() == "remote")
        jobspy_type = _JOB_TYPE_MAP.get(job_type) if job_type else None

        df: pd.DataFrame = scrape_jobs(
            site_name=_SITES,
            search_term=query,
            location=None if is_remote else (location or ""),
            results_wanted=limit,
            job_type=jobspy_type,
            is_remote=is_remote,
            hours_old=168,
            verbose=0,
        )

        listings: list[JobListing] = []
        for _, row in df.iterrows():
            listings.append(
                JobListing(
                    title=_str(row.get("title")),
                    company=_str(row.get("company")),
                    location=_str(row.get("location")),
                    job_type=_normalize_type(row.get("job_type")),
                    url=_str(row.get("job_url") or row.get("job_url_direct")),
                    source=_str(row.get("site")).capitalize(),
                    posted_date=_date_str(row.get("date_posted")),
                    salary_range=_format_salary(row),
                )
            )
        return listings


def _str(val: object) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _date_str(val: object) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return str(val)


def _normalize_type(raw: object) -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    return _REVERSE_TYPE_MAP.get(str(raw).lower(), str(raw).lower())


def _format_salary(row: pd.Series) -> str | None:
    min_amt = row.get("min_amount")
    max_amt = row.get("max_amount")
    interval = _str(row.get("interval"))

    has_min = min_amt is not None and not (isinstance(min_amt, float) and pd.isna(min_amt))
    has_max = max_amt is not None and not (isinstance(max_amt, float) and pd.isna(max_amt))

    if not has_min and not has_max:
        return None

    parts: list[str] = []
    if has_min:
        parts.append(f"${float(min_amt):,.0f}")
    if has_max and max_amt != min_amt:
        parts.append(f"${float(max_amt):,.0f}")

    base = " - ".join(parts)
    return f"{base} /{interval}".strip(" /") if interval else base
