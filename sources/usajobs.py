from __future__ import annotations

import os

from models import JobListing
from sources.base import JobSource


USAJOBS_ENDPOINT = "https://data.usajobs.gov/api/search"


class USAJobsSource(JobSource):
    name = "USAJobs"

    def __init__(self) -> None:
        super().__init__()
        user_agent = os.getenv("USAJOBS_USER_AGENT")
        auth_key = os.getenv("USAJOBS_AUTH_KEY")
        if not user_agent or not auth_key:
            raise ValueError(
                "USAJobs requires USAJOBS_USER_AGENT (your contact email) and "
                "USAJOBS_AUTH_KEY environment variables. Set them in your .env "
                "file or environment."
            )
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Authorization-Key": auth_key,
            }
        )

    def search(
        self,
        query: str,
        job_type: str | None,
        location: str | None,
        limit: int,
    ) -> list[JobListing]:
        params: dict[str, str | int] = {"Keyword": query, "ResultsPerPage": limit}
        if location:
            params["LocationName"] = location

        response = self.session.get(USAJOBS_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()

        items = (
            payload.get("SearchResult", {}).get("SearchResultItems", []) or []
        )

        listings: list[JobListing] = []
        for item in items:
            descriptor = item.get("MatchedObjectDescriptor", {}) or {}
            offering_types = descriptor.get("PositionOfferingType", []) or []
            offering_name = (
                offering_types[0].get("Name", "") if offering_types else ""
            )

            remuneration = descriptor.get("PositionRemuneration", []) or []
            salary = _format_remuneration(remuneration[0] if remuneration else None)

            listings.append(
                JobListing(
                    title=descriptor.get("PositionTitle", ""),
                    company=descriptor.get("OrganizationName", ""),
                    location=descriptor.get("PositionLocationDisplay", ""),
                    job_type=offering_name,
                    url=descriptor.get("PositionURI", ""),
                    source=self.name,
                    posted_date=descriptor.get("PublicationStartDate"),
                    salary_range=salary,
                )
            )
        return listings


def _format_remuneration(entry: dict | None) -> str | None:
    if not entry:
        return None
    minimum = entry.get("MinimumRange")
    maximum = entry.get("MaximumRange")
    interval = entry.get("RateIntervalCode") or ""
    if not minimum and not maximum:
        return None
    parts: list[str] = []
    if minimum:
        parts.append(f"${float(minimum):,.0f}")
    if maximum and maximum != minimum:
        parts.append(f"${float(maximum):,.0f}")
    base = " - ".join(parts)
    return f"{base} {interval}".strip()
