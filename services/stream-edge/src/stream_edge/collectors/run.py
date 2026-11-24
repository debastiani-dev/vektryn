import argparse
import asyncio
import logging
import os

import httpx

from stream_edge.collectors.ashby import AshbyCollector
from stream_edge.collectors.ats_boards import (
    BreezyCollector,
    InHireCollector,
    LeverCollector,
    RecruiteeCollector,
    SmartRecruitersCollector,
    WorkableCollector,
)
from stream_edge.collectors.base import (
    BaseATSCollector,
    CollectedJob,
    push_jobs_to_edge,
)
from stream_edge.collectors.discovery import discover_all_ats_boards
from stream_edge.collectors.greenhouse import GreenhouseCollector
from stream_edge.collectors.prefilter import (
    ResumeFilterCriteria,
    filter_and_rank_jobs,
    load_resume_criteria,
)
from stream_edge.collectors.remote_feeds import MultiCompanyFeedCollector
from stream_edge.collectors.taxonomy import sync_dynamic_stacks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _board_label(token: str) -> str:
    return token.replace("-", " ").replace("_", " ").title()


async def _collect_board(
    collector: BaseATSCollector,
    source_name: str,
    board_token: str,
    criteria: ResumeFilterCriteria | None,
    dynamic_stacks: frozenset[str],
    max_per_board: int,
    min_skill_matches: int,
    semaphore: asyncio.Semaphore,
) -> list[CollectedJob]:
    async with semaphore:
        try:
            raw_jobs = await collector.fetch_board(
                board_token=board_token,
                company_name=_board_label(board_token),
            )
        except Exception as exc:
            logger.debug("Board %s[%s] skipped: %s", source_name, board_token, exc)
            return []

    matched = filter_and_rank_jobs(
        raw_jobs,
        criteria,
        dynamic_stacks=dynamic_stacks,
        min_skill_matches=min_skill_matches,
    )
    if matched:
        logger.info(
            "%s[%s]: %d/%d postings survived resume pre-filter",
            source_name,
            board_token,
            len(matched),
            len(raw_jobs),
        )
    return matched[:max_per_board]


async def run_collection(
    *,
    edge_url: str = "http://localhost:8001",
    max_per_board: int = 8,
    boards_per_ats: int = 25,
    max_total: int = 30,
    resume_id: str | None = None,
    min_skill_matches: int = 2,
    refresh_discovery: bool = False,
) -> None:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # 1. Sync dynamic language/framework catalog (cached in Redis) & load resume criteria
        dynamic_stacks = await sync_dynamic_stacks(
            client, force_refresh=refresh_discovery
        )
        criteria = await asyncio.to_thread(
            load_resume_criteria,
            resume_id,
            dynamic_stacks=dynamic_stacks,
        )

        # 2. Global + Brazilian multi-company feeds (Remotive, Himalayas, Jobicy, Gupy, Trampos, GitHub Vagas)
        feed_collector = MultiCompanyFeedCollector(http_client=client)
        raw_feed_jobs = await feed_collector.fetch_all()
        feed_candidates = filter_and_rank_jobs(
            raw_feed_jobs,
            criteria,
            dynamic_stacks=dynamic_stacks,
            min_skill_matches=min_skill_matches,
        )
        logger.info(
            "Multi-company feeds (Global + BR): %d/%d postings survived resume pre-filter",
            len(feed_candidates),
            len(raw_feed_jobs),
        )

        # 3. Dynamic discovery & verification across all 8 Global + BR ATS platforms
        board_pools = await discover_all_ats_boards(
            client,
            seed_jobs=raw_feed_jobs,
            force_refresh=refresh_discovery,
        )

        collectors: dict[str, BaseATSCollector] = {
            "greenhouse": GreenhouseCollector(http_client=client),
            "ashby": AshbyCollector(http_client=client),
            "lever": LeverCollector(http_client=client),
            "workable": WorkableCollector(http_client=client),
            "smartrecruiters": SmartRecruitersCollector(http_client=client),
            "recruitee": RecruiteeCollector(http_client=client),
            "breezy": BreezyCollector(http_client=client),
            "inhire": InHireCollector(http_client=client),
        }

        sem = asyncio.Semaphore(12)
        board_tasks = [
            _collect_board(
                collector,
                ats_name,
                token,
                criteria,
                dynamic_stacks,
                max_per_board,
                min_skill_matches,
                sem,
            )
            for ats_name, collector in collectors.items()
            for token in board_pools.sample(ats_name, boards_per_ats)
        ]

        board_batches = await asyncio.gather(*board_tasks)
        ats_candidates = [job for batch in board_batches for job in batch]

        # 4. Merge, globally rank by resume skill overlap, and cap batch size
        merged = filter_and_rank_jobs(
            [*feed_candidates, *ats_candidates],
            criteria,
            dynamic_stacks=dynamic_stacks,
            min_skill_matches=min_skill_matches,
        )[:max_total]

        pushed = await push_jobs_to_edge(
            http_client=client,
            edge_base_url=edge_url,
            jobs=merged,
        )

    logger.info(
        "Collection complete: pushed %d / %d top-ranked postings to %s",
        pushed,
        len(merged),
        edge_url,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Vektryn Global + Brazil ATS & feed collectors"
    )
    parser.add_argument("--resume-id", default=os.getenv("COLLECT_RESUME_ID") or None)
    parser.add_argument(
        "--min-skills", type=int, default=int(os.getenv("COLLECT_MIN_SKILLS", "2"))
    )
    parser.add_argument(
        "--max-total", type=int, default=int(os.getenv("COLLECT_MAX_TOTAL", "30"))
    )
    parser.add_argument(
        "--boards-per-ats",
        type=int,
        default=int(os.getenv("COLLECT_BOARDS_PER_ATS", "25")),
    )
    parser.add_argument("--refresh-discovery", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    edge = os.getenv("STREAM_EDGE_URL", "http://localhost:8001")
    cap_per_board = int(os.getenv("COLLECT_MAX_PER_BOARD", "8"))
    asyncio.run(
        run_collection(
            edge_url=edge,
            max_per_board=cap_per_board,
            boards_per_ats=args.boards_per_ats,
            max_total=args.max_total,
            resume_id=args.resume_id,
            min_skill_matches=args.min_skills,
            refresh_discovery=args.refresh_discovery,
        )
    )
