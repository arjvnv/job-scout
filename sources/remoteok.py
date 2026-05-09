from __future__ import annotations

from models import JobListing
from sources.base import JobSource


REMOTEOK_ENDPOINT = "https://remoteok.com/api"


class RemoteOKSource(JobSource):
    name = "RemoteOK"

    def search(
        self,
        query: str,
        job_type: str | None,
        location: str | None,
        limit: int,
    ) -> list[JobListing]:
        response = self.session.get(REMOTEOK_ENDPOINT, timeout=15)
        response.raise_for_status()
        payload = response.json()

        # The RemoteOK API returns a metadata dict as the first element followed
        # by the job entries. Skip the metadata.
        if payload and isinstance(payload[0], dict) and "legal" in payload[0]:
            entries = payload[1:]
        else:
            entries = payload

        query_words = [w for w in query.lower().split() if len(w) >= 3]

        listings: list[JobListing] = []
        for item in entries:
            title = (item.get("position") or "").strip()
            if query_words and not any(w in title.lower() for w in query_words):
                continue

            tags = [str(t).lower() for t in item.get("tags", [])]
            inferred_type = _infer_job_type(tags)

            listings.append(
                JobListing(
                    title=title,
                    company=item.get("company", ""),
                    location=item.get("location") or "Remote",
                    job_type=inferred_type,
                    url=item.get("url", ""),
                    source=self.name,
                    posted_date=item.get("date"),
                    salary_range=_format_salary(
                        item.get("salary_min"), item.get("salary_max")
                    ),
                )
            )
            if len(listings) >= limit:
                break
        return listings


def _infer_job_type(tags: list[str]) -> str:
    for candidate in ("internship", "contract", "part-time", "full-time"):
        if candidate in tags or candidate.replace("-", "_") in tags:
            return candidate
    return "remote"


def _format_salary(salary_min: float | None, salary_max: float | None) -> str | None:
    if not salary_min and not salary_max:
        return None
    if salary_min and salary_max:
        return f"${int(salary_min):,} - ${int(salary_max):,}"
    if salary_min:
        return f"${int(salary_min):,}+"
    return f"up to ${int(salary_max):,}"
