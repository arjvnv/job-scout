from __future__ import annotations

from models import JobListing
from sources.base import JobSource


REMOTIVE_ENDPOINT = "https://remotive.com/api/remote-jobs"


_JOB_TYPE_MAP = {
    "full_time": "full-time",
    "part_time": "part-time",
    "contract": "contract",
    "freelance": "contract",
    "internship": "internship",
    "other": "other",
}


class RemotiveSource(JobSource):
    name = "Remotive"

    def search(
        self,
        query: str,
        job_type: str | None,
        location: str | None,
        limit: int,
    ) -> list[JobListing]:
        params: dict[str, str | int] = {"search": query, "limit": min(limit * 3, 100)}
        response = self.session.get(REMOTIVE_ENDPOINT, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()

        listings: list[JobListing] = []
        for item in payload.get("jobs", []):
            raw_type = (item.get("job_type") or "").lower()
            normalized_type = _JOB_TYPE_MAP.get(raw_type, raw_type)
            listings.append(
                JobListing(
                    title=item.get("title", "").strip(),
                    company=item.get("company_name", ""),
                    location=item.get("candidate_required_location", "Remote"),
                    job_type=normalized_type,
                    url=item.get("url", ""),
                    source=self.name,
                    posted_date=item.get("publication_date"),
                    salary_range=item.get("salary") or None,
                )
            )
        return listings
