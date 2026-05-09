from __future__ import annotations

from bs4 import BeautifulSoup

from models import JobListing
from sources.base import JobSource


WWR_BASE = "https://weworkremotely.com"
WWR_SEARCH = f"{WWR_BASE}/remote-jobs/search"


class WeWorkRemotelySource(JobSource):
    name = "WeWorkRemotely"

    def search(
        self,
        query: str,
        job_type: str | None,
        location: str | None,
        limit: int,
    ) -> list[JobListing]:
        response = self.session.get(
            WWR_SEARCH, params={"term": query}, timeout=15
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        listings: list[JobListing] = []
        for section in soup.select("section.jobs"):
            for li in section.select("li"):
                anchors = li.find_all("a", href=True)
                if not anchors:
                    continue
                # WWR list items typically include a "view all" anchor as well as
                # the job link. Pick the first anchor that has a title node.
                job_anchor = next(
                    (a for a in anchors if a.select_one(".title")), None
                )
                if job_anchor is None:
                    continue

                title_el = job_anchor.select_one(".title")
                company_el = job_anchor.select_one(".company")
                region_el = job_anchor.select_one(".region")

                title = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""
                location_text = (
                    region_el.get_text(strip=True) if region_el else "Remote"
                )

                href = job_anchor["href"]
                url = href if href.startswith("http") else f"{WWR_BASE}{href}"

                listings.append(
                    JobListing(
                        title=title,
                        company=company,
                        location=location_text or "Remote",
                        job_type="remote",
                        url=url,
                        source=self.name,
                        posted_date=None,
                        salary_range=None,
                    )
                )
                if len(listings) >= limit:
                    return listings
        return listings
