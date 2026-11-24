from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from pathlib import Path

import httpx
import redis.asyncio as aioredis

from stream_edge.config import settings
from vektryn_contracts.enums import TechCategory

logger = logging.getLogger(__name__)

_TAXONOMY_PATH = Path(__file__).parent / "data" / "tech_taxonomy.json"
_DEVICON_URL = "https://raw.githubusercontent.com/devicons/devicon/master/devicon.json"
_TAXONOMY_CACHE_KEY = "vektryn:taxonomy:dynamic_stacks:v1"
_TAXONOMY_CACHE_TTL = 60 * 60 * 24 * 7  # 7 days

# Devicon tags that represent programming languages or application frameworks (excludes OS/fonts/browsers/editors)
_RELEVANT_DEVICON_TAGS = frozenset({"language", "framework", "library"})


@dataclass(frozen=True)
class TechTaxonomy:
    software_role_keywords: tuple[str, ...]
    primary_stacks: frozenset[str]
    disciplines: dict[str, tuple[str, ...]]
    seniority_markers: dict[str, tuple[str, ...]]
    remote_markers: tuple[str, ...]
    tag_to_category: dict[str, str]


def _extract_devicon_stacks(entries: list[dict]) -> list[str]:
    stacks: set[str] = set()
    for entry in entries:
        tags = {t.lower() for t in (entry.get("tags") or [])}
        if not (tags & _RELEVANT_DEVICON_TAGS):
            continue

        candidates = [entry.get("name"), *(entry.get("altnames") or [])]
        for raw in candidates:
            clean = str(raw or "").strip().lower()
            if len(clean) >= 2:
                stacks.add(clean)
    return sorted(stacks)


def _build_tag_category_map(raw_categories: dict[str, list[str]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for raw_cat, tags in raw_categories.items():
        category = TechCategory(raw_cat.strip().lower()).value
        for tag in tags:
            clean_tag = tag.strip().lower()
            if clean_tag:
                mapping[clean_tag] = category
    return mapping


async def sync_dynamic_stacks(
    client: httpx.AsyncClient,
    *,
    force_refresh: bool = False,
) -> frozenset[str]:
    """Fetch curated languages and frameworks from Devicon and cache in Redis."""
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        if not force_refresh:
            cached = await redis_client.get(_TAXONOMY_CACHE_KEY)
            if cached:
                return frozenset(json.loads(cached))

        resp = await client.get(_DEVICON_URL, timeout=15.0)
        resp.raise_for_status()
        sorted_stacks = _extract_devicon_stacks(resp.json())

        if sorted_stacks:
            await redis_client.setex(
                _TAXONOMY_CACHE_KEY,
                _TAXONOMY_CACHE_TTL,
                json.dumps(sorted_stacks),
            )
        logger.info("Synced %d languages/frameworks from Devicon", len(sorted_stacks))
        return frozenset(sorted_stacks)
    except Exception as exc:
        logger.warning("Failed to sync Devicon taxonomy; using local fallback: %s", exc)
        return frozenset()
    finally:
        await redis_client.aclose()


@lru_cache(maxsize=2)
def load_taxonomy(dynamic_stacks: frozenset[str] = frozenset()) -> TechTaxonomy:
    raw = json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))
    stacks = frozenset(s.lower() for s in raw["primary_stacks"]) | dynamic_stacks
    return TechTaxonomy(
        software_role_keywords=tuple(raw["software_role_keywords"]),
        primary_stacks=stacks,
        disciplines={k: tuple(v) for k, v in raw["disciplines"].items()},
        seniority_markers={k: tuple(v) for k, v in raw["seniority_markers"].items()},
        remote_markers=tuple(raw["remote_markers"]),
        tag_to_category=_build_tag_category_map(raw.get("categories", {})),
    )
