import asyncio
from dataclasses import dataclass
import json
import logging
import random
import re

import httpx
import redis.asyncio as aioredis

from stream_edge.collectors.base import CollectedJob
from stream_edge.collectors.prefilter import ResumeFilterCriteria
from stream_edge.config import settings

logger = logging.getLogger(__name__)

_DISCOVERY_CACHE_KEY = "vektryn:discovery:verified_boards:v8"
_DISCOVERY_CACHE_TTL = 60 * 60 * 24 * 7  # 7 days
_PROBE_CONCURRENCY = 40
_MAX_CANDIDATES_PER_ATS = 300

_ATS_REGEXES: dict[str, re.Pattern[str]] = {
    "greenhouse": re.compile(
        r"https?://(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/([a-zA-Z0-9_-]{2,60})",
        re.IGNORECASE,
    ),
    "ashby": re.compile(
        r"https?://jobs\.ashbyhq\.com/([a-zA-Z0-9_.-]{2,60})",
        re.IGNORECASE,
    ),
    "lever": re.compile(
        r"https?://jobs(?:\.eu)?\.lever\.co/([a-zA-Z0-9_-]{2,60})",
        re.IGNORECASE,
    ),
    "workable": re.compile(
        r"https?://apply\.workable\.com/([a-zA-Z0-9_-]{2,60})",
        re.IGNORECASE,
    ),
    "smartrecruiters": re.compile(
        r"https?://jobs\.smartrecruiters\.com/([a-zA-Z0-9_-]{2,60})",
        re.IGNORECASE,
    ),
    "recruitee": re.compile(
        r"https?://([a-zA-Z0-9_-]{2,60})\.recruitee\.com",
        re.IGNORECASE,
    ),
    "breezy": re.compile(
        r"https?://([a-zA-Z0-9_-]{2,60})\.breezy\.hr",
        re.IGNORECASE,
    ),
    "inhire": re.compile(
        r"https?://([a-zA-Z0-9_-]{2,60})\.inhire\.app",
        re.IGNORECASE,
    ),
}

_IGNORED_SLUGS = frozenset({
    "www",
    "api",
    "app",
    "jobs",
    "boards",
    "job-boards",
    "apply",
    "careers",
    "embed",
    "v1",
    "v0",
    "public",
    "static",
    "assets",
    "support",
    "help",
    "blog",
    "status",
    "mail",
    "cdn",
})

_PUBLIC_COMPANY_INDEX_URLS = (
    "https://raw.githubusercontent.com/remoteintech/remote-jobs/main/README.md",
    "https://raw.githubusercontent.com/poteto/hiring-without-whiteboards/main/README.md",
    "https://raw.githubusercontent.com/yanirs/established-remote/master/README.md",
    "https://raw.githubusercontent.com/lukasz-madon/awesome-remote-job/master/README.md",
    "https://raw.githubusercontent.com/tramcar/awesome-job-boards/master/README.md",
)

_YC_HIRING_COMPANIES_URL = "https://yc-oss.github.io/api/companies/hiring.json"
_YC_PROBE_ATS = ("greenhouse", "ashby", "lever")
_PER_HOST_CONCURRENCY = 4


@dataclass
class DiscoveredBoards:
    pools: dict[str, list[str]]

    def sample(self, ats: str, limit: int) -> list[str]:
        tokens = list(self.pools.get(ats, []))
        random.shuffle(tokens)
        return tokens[:limit]


def extract_slugs_from_text(text: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {ats: set() for ats in _ATS_REGEXES}
    for ats, pattern in _ATS_REGEXES.items():
        for match in pattern.finditer(text):
            slug = match.group(1).strip().lower().rstrip("/")
            if slug and slug not in _IGNORED_SLUGS and not slug.startswith("."):
                found[ats].add(slug)
    return found


def _merge_slug_maps(target: dict[str, set[str]], incoming: dict[str, set[str]]) -> None:
    for ats, slugs in incoming.items():
        target.setdefault(ats, set()).update(slugs)


async def _harvest_github_company_indexes(client: httpx.AsyncClient) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {ats: set() for ats in _ATS_REGEXES}

    async def _fetch_one(url: str) -> str:
        resp = await client.get(url, timeout=15.0)
        resp.raise_for_status()
        return resp.text

    results = await asyncio.gather(
        *(_fetch_one(url) for url in _PUBLIC_COMPANY_INDEX_URLS),
        return_exceptions=True,
    )
    for url, res in zip(_PUBLIC_COMPANY_INDEX_URLS, results, strict=True):
        if isinstance(res, Exception):
            logger.debug("GitHub company index fetch skipped (%s): %s", url, res)
            continue
        _merge_slug_maps(found, extract_slugs_from_text(res))
    return found


async def _harvest_yc_hiring_slugs(client: httpx.AsyncClient) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {ats: set() for ats in _ATS_REGEXES}
    try:
        resp = await client.get(_YC_HIRING_COMPANIES_URL, timeout=15.0)
        resp.raise_for_status()
        companies = resp.json()
    except Exception as exc:
        logger.debug("YC hiring directory skipped: %s", exc)
        return found

    slugs: list[str] = []
    for company in companies:
        if not isinstance(company, dict):
            continue
        slug = str(company.get("slug") or "").strip().lower()
        if slug and slug not in _IGNORED_SLUGS and re.fullmatch(r"[a-z0-9-]{2,50}", slug):
            slugs.append(slug)

    random.shuffle(slugs)
    sampled = slugs[:_MAX_CANDIDATES_PER_ATS]
    for ats in _YC_PROBE_ATS:
        found[ats].update(sampled)
    return found


def _harvest_from_seed_jobs(seed_jobs: list[CollectedJob]) -> dict[str, set[str]]:
    blob = "\n".join(
        f"{j.apply_url}\n{j.raw_html[:3000]}"
        for j in seed_jobs
    )
    return extract_slugs_from_text(blob)


def _probe_request_spec(ats: str, slug: str) -> tuple[str, dict[str, str]]:
    specs: dict[str, tuple[str, dict[str, str]]] = {
        "greenhouse": (f"https://boards-api.greenhouse.io/v1/boards/{slug}", {}),
        "ashby": (f"https://api.ashbyhq.com/posting-api/job-board/{slug}", {}),
        "lever": (f"https://api.lever.co/v0/postings/{slug}?limit=1", {}),
        "workable": (f"https://apply.workable.com/api/v1/widget/accounts/{slug}", {}),
        "smartrecruiters": (f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1", {}),
        "recruitee": (f"https://{slug}.recruitee.com/api/offers/", {}),
        "breezy": (f"https://{slug}.breezy.hr/json", {}),
        "inhire": ("https://api.inhire.app/job-posts/public/pages", {"X-Tenant": slug}),
    }
    return specs[ats]


async def _is_valid_ats_board(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    ats: str,
    slug: str,
) -> bool:
    url, headers = _probe_request_spec(ats, slug)
    async with sem:
        try:
            resp = await client.get(url, headers=headers, timeout=6.0)
            if resp.status_code != 200:
                return False
            if ats == "smartrecruiters":
                data = resp.json()
                return isinstance(data, dict) and data.get("totalFound", 0) > 0
            return True
        except Exception:
            return False


async def _verify_candidate_pools(
    client: httpx.AsyncClient,
    candidates: dict[str, set[str]],
) -> dict[str, list[str]]:
    """Validate candidate slugs concurrently with per-host rate limiting."""
    global_sem = asyncio.Semaphore(_PROBE_CONCURRENCY)
    host_sems = {ats: asyncio.Semaphore(_PER_HOST_CONCURRENCY) for ats in _ATS_REGEXES}
    tasks: list[tuple[str, str, asyncio.Task[bool]]] = []

    async def _bounded_probe(ats: str, slug: str) -> bool:
        async with host_sems[ats]:
            return await _is_valid_ats_board(client, global_sem, ats, slug)

    async with asyncio.TaskGroup() as tg:
        for ats, slugs in candidates.items():
            for slug in sorted(slugs):
                task = tg.create_task(_bounded_probe(ats, slug))
                tasks.append((ats, slug, task))

    verified: dict[str, list[str]] = {ats: [] for ats in _ATS_REGEXES}
    for ats, slug, task in tasks:
        if task.result():
            verified[ats].append(slug)

    return verified


async def _refresh_cached_pools_with_seeds(
    client: httpx.AsyncClient,
    redis_client: aioredis.Redis,
    pools: dict[str, list[str]],
    seed_jobs: list[CollectedJob],
) -> dict[str, list[str]]:
    seed_hits = _harvest_from_seed_jobs(seed_jobs)
    new_candidates = {
        ats: slugs - set(pools.get(ats, []))
        for ats, slugs in seed_hits.items()
        if slugs - set(pools.get(ats, []))
    }
    if not new_candidates:
        return pools

    verified_seeds = await _verify_candidate_pools(client, new_candidates)
    for ats, valid_slugs in verified_seeds.items():
        pools[ats] = sorted(set(pools.get(ats, [])) | set(valid_slugs))

    await redis_client.setex(
        _DISCOVERY_CACHE_KEY,
        _DISCOVERY_CACHE_TTL,
        json.dumps(pools),
    )
    return pools


async def discover_all_ats_boards(
    client: httpx.AsyncClient,
    seed_jobs: list[CollectedJob] | None = None,
    *,
    force_refresh: bool = False,
) -> DiscoveredBoards:
    """Discover and verify active company ATS boards across 8 platforms and cache in Redis."""
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        if not force_refresh:
            cached = await redis_client.get(_DISCOVERY_CACHE_KEY)
            if cached:
                pools = json.loads(cached)
                if seed_jobs:
                    pools = await _refresh_cached_pools_with_seeds(
                        client, redis_client, pools, seed_jobs
                    )
                return DiscoveredBoards(pools=pools)

        candidates: dict[str, set[str]] = {ats: set() for ats in _ATS_REGEXES}
        gh_hits, yc_hits = await asyncio.gather(
            _harvest_github_company_indexes(client),
            _harvest_yc_hiring_slugs(client),
        )
        _merge_slug_maps(candidates, gh_hits)
        _merge_slug_maps(candidates, yc_hits)

        if seed_jobs:
            _merge_slug_maps(candidates, _harvest_from_seed_jobs(seed_jobs))

        pools = await _verify_candidate_pools(client, candidates)
        if any(pools.values()):
            await redis_client.setex(
                _DISCOVERY_CACHE_KEY,
                _DISCOVERY_CACHE_TTL,
                json.dumps(pools),
            )

        summary = ", ".join(f"{ats}={len(slugs)}" for ats, slugs in pools.items())
        logger.info("Verified ATS discovery pools (0 dead boards): %s", summary)
        return DiscoveredBoards(pools=pools)
    finally:
        await redis_client.aclose()