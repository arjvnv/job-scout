from __future__ import annotations

from abc import ABC, abstractmethod

import requests

from models import JobListing


class JobSource(ABC):
    name: str = ""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "job-scout/1.0"})

    @abstractmethod
    def search(
        self,
        query: str,
        job_type: str | None,
        location: str | None,
        limit: int,
    ) -> list[JobListing]:
        ...
