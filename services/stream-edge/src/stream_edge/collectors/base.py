import html
import logging
from abc import ABC, abstractmethod
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, HttpUrl

from stream_edge.config import settings
from vektryn_contracts import ATSSource

logger = logging.getLogger(__name__)


class CollectedJob(BaseModel):
    ats_source: ATSSource
    external_id: str
    title: str
    company_name: str
    apply_url: HttpUrl
    location_raw: str = ""
    raw_html: str
    description_clean: str
    posted_at: datetime | None = None


def html_to_clean_text(raw_html: str) -> str:
    """Unescapes ATS HTML entities and extracts clean readable text."""
    unescaped = html.unescape(raw_html or "")
    soup = BeautifulSoup(unescaped, "html.parser")
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    return "\n".join(lines)


class BaseATSCollector(ABC):
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    @abstractmethod
    async def fetch_board(
        self, board_token: str, company_name: str
    ) -> list[CollectedJob]:
        raise NotImplementedError


async def push_jobs_with_stats(
    *,
    http_client: httpx.AsyncClient,
    edge_base_url: str,
    jobs: list[CollectedJob],
    ingest_api_key: str | None = None,
) -> dict[str, tuple[int, int]]:
    """Pushes collected jobs and returns {ats_source: (accepted_count, error_count)}."""
    endpoint = f"{edge_base_url.rstrip('/')}/ingest/jobs"
    api_key = (
        ingest_api_key if ingest_api_key is not None else settings.ingest_api_key
    ).strip()
    headers = {"X-Ingest-API-Key": api_key} if api_key else {}
    counts: dict[str, tuple[int, int]] = {}
    for job in jobs:
        source_key = job.ats_source.value
        accepted, errors = counts.get(source_key, (0, 0))
        try:
            resp = await http_client.post(
                endpoint,
                json=job.model_dump(mode="json"),
                headers=headers,
                timeout=15.0,
            )
            resp.raise_for_status()
            counts[source_key] = (accepted + 1, errors)
        except httpx.HTTPError as exc:
            counts[source_key] = (accepted, errors + 1)
            logger.warning(
                "Failed pushing %s:%s to edge: %s",
                source_key,
                job.external_id,
                exc,
            )
    return counts


async def push_jobs_to_edge(
    *,
    http_client: httpx.AsyncClient,
    edge_base_url: str,
    jobs: list[CollectedJob],
    ingest_api_key: str | None = None,
) -> int:
    stats = await push_jobs_with_stats(
        http_client=http_client,
        edge_base_url=edge_base_url,
        jobs=jobs,
        ingest_api_key=ingest_api_key,
    )
    return sum(accepted for accepted, _ in stats.values())
