from __future__ import annotations

import os

from models import JobListing
from sources.base import JobSource


ADZUNA_ENDPOINT = "https://api.adzuna.com/v1/api/jobs/us/search/1"


class AdzunaSource(JobSource):
    name = "Adzuna"

    def __init__(self) -> None:
        super().__init__()
        app_id = os.getenv("ADZUNA_APP_ID")
        app_key = os.getenv("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            raise ValueError(
                "Adzuna requires ADZUNA_APP_ID and ADZUNA_APP_KEY environment "
                "variables. Set them in your .env file or environment."
            )
        self.app_id = app_id
        self.app_key = app_key

    def search(
        self,
        query: str,
        job_type: str | None,
        location: str | None,
        limit: int,
    ) -> list[JobListing]:
        effective_query = query
        params: dict[str, str | int] = {
            "app_id": self.app_id,
            "app_key": self.app_key,
            "results_per_page": limit,
            "content-type": "application/json",
        }

        if job_type == "full-time" or job_type == "full_time":
            params["full_time"] = 1
        elif job_type == "part-time" or job_type == "part_time":
            params["part_time"] = 1
        elif job_type == "internship":
            effective_query = f"{query} intern".strip()

        params["what"] = effective_query
        if location:
            params["where"] = location

        response = self.session.get(ADZUNA_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()

        listings: list[JobListing] = []
        for item in payload.get("results", []):
            listings.append(
                JobListing(
                    title=item.get("title", "").strip(),
                    company=(item.get("company") or {}).get("display_name", ""),
                    location=(item.get("location") or {}).get("display_name", ""),
                    job_type=item.get("contract_type", "") or "",
                    url=item.get("redirect_url", ""),
                    source=self.name,
                    posted_date=item.get("created"),
                    salary_range=_format_salary(
                        item.get("salary_min"), item.get("salary_max")
                    ),
                )
            )
        return listings


def _format_salary(salary_min: float | None, salary_max: float | None) -> str | None:
    if salary_min is None and salary_max is None:
        return None
    if salary_min is not None and salary_max is not None:
        return f"${int(salary_min):,} - ${int(salary_max):,}"
    if salary_min is not None:
        return f"${int(salary_min):,}+"
    return f"up to ${int(salary_max):,}"
