from __future__ import annotations

import os

from dotenv import load_dotenv

from sources.adzuna import AdzunaSource
from sources.base import JobSource
from sources.jobspy_source import JobSpySource
from sources.remoteok import RemoteOKSource
from sources.remotive import RemotiveSource
from sources.usajobs import USAJobsSource
from sources.weworkremotely import WeWorkRemotelySource


load_dotenv()

ADZUNA_APP_ID: str | None = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY: str | None = os.getenv("ADZUNA_APP_KEY")

DEFAULT_LIMIT: int = 50


def _build_registry() -> list[JobSource]:
    registry: list[JobSource] = [
        JobSpySource(),
        RemotiveSource(),
        RemoteOKSource(),
        WeWorkRemotelySource(),
    ]

    for cls, label in [
        (AdzunaSource, "Adzuna"),
        (USAJobsSource, "USAJobs"),
    ]:
        try:
            registry.append(cls())
        except ValueError:
            pass

    return registry


SOURCE_REGISTRY: list[JobSource] = _build_registry()
