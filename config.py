from __future__ import annotations

import os

from dotenv import load_dotenv

from sources.adzuna import AdzunaSource
from sources.base import JobSource
from sources.remoteok import RemoteOKSource
from sources.remotive import RemotiveSource
from sources.usajobs import USAJobsSource
from sources.weworkremotely import WeWorkRemotelySource


load_dotenv()

ADZUNA_APP_ID: str | None = os.getenv("ADZUNA_APP_ID")
ADZUNA_APP_KEY: str | None = os.getenv("ADZUNA_APP_KEY")

DEFAULT_LIMIT: int = 20


def _build_registry() -> list[JobSource]:
    registry: list[JobSource] = []

    try:
        registry.append(AdzunaSource())
    except ValueError:
        # Adzuna requires API credentials; skip silently when absent so the
        # tool remains usable with the free sources alone.
        pass

    registry.extend(
        [
            RemotiveSource(),
            RemoteOKSource(),
        ]
    )

    try:
        registry.append(USAJobsSource())
    except ValueError:
        # USAJobs requires USAJOBS_USER_AGENT and USAJOBS_AUTH_KEY; skip
        # silently when absent so the tool remains usable with free sources.
        pass

    registry.append(WeWorkRemotelySource())
    return registry


SOURCE_REGISTRY: list[JobSource] = _build_registry()
