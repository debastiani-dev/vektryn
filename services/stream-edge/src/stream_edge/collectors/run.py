import asyncio
import logging
import os

import httpx

from stream_edge.collectors.ashby import AshbyCollector
from stream_edge.collectors.base import CollectedJob, push_jobs_to_edge
from stream_edge.collectors.greenhouse import GreenhouseCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Curated public tech boards (board_token, display_company_name)
GREENHOUSE_BOARDS: list[tuple[str, str]] = [
    ("gitlab", "GitLab"),
    ("canonical", "Canonical"),
    ("cloudflare", "Cloudflare"),
]

ASHBY_BOARDS: list[tuple[str, str]] = [
    ("linear", "Linear"),
    ("supabase", "Supabase"),
    ("ramp", "Ramp"),
]

ENGINEERING_KEYWORDS = (
    "engineer",
    "developer",
    "backend",
    "back-end",
    "python",
    "django",
    "software",
    "platform",
    "infrastructure",
    "sre",
    "distributed",
)


def _is_engineering_role(title: str) -> bool:
    lowered = title.lower()
    return any(kw in lowered for kw in ENGINEERING_KEYWORDS)


async def run_collection() -> None:
    edge_url = os.getenv("STREAM_EDGE_URL", "http://localhost:8001")
    max_per_board = int(os.getenv("COLLECT_MAX_PER_BOARD", "15"))

    async with httpx.AsyncClient(
        headers={"User-Agent": "VektrynBot/0.1 (+https://vektryn.debastiani.dev)"}
    ) as client:
        gh = GreenhouseCollector(client)
        ashby = AshbyCollector(client)

        tasks = [
            *(gh.fetch_board(token, name) for token, name in GREENHOUSE_BOARDS),
            *(ashby.fetch_board(token, name) for token, name in ASHBY_BOARDS),
        ]
        batches = await asyncio.gather(*tasks, return_exceptions=True)

        filtered_jobs: list[CollectedJob] = []
        for batch in batches:
            if isinstance(batch, Exception):
                logger.warning("Board collection error: %s", batch)
                continue
            eng_jobs = [j for j in batch if _is_engineering_role(j.title)][:max_per_board]
            filtered_jobs.extend(eng_jobs)

        accepted = await push_jobs_to_edge(
            http_client=client,
            edge_base_url=edge_url,
            jobs=filtered_jobs,
        )
        logger.info(
            "Collection complete: pushed %d / %d engineering postings to %s",
            accepted,
            len(filtered_jobs),
            edge_url,
        )


if __name__ == "__main__":
    asyncio.run(run_collection())