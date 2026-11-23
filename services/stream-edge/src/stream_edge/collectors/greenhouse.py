import logging
from datetime import datetime

from stream_edge.collectors.base import BaseATSCollector, CollectedJob, html_to_clean_text
from vektryn_contracts import ATSSource

logger = logging.getLogger(__name__)


class GreenhouseCollector(BaseATSCollector):
    BASE_URL = "https://boards-api.greenhouse.io/v1/boards"

    async def fetch_board(self, board_token: str, company_name: str) -> list[CollectedJob]:
        url = f"{self.BASE_URL}/{board_token}/jobs"
        resp = await self.http_client.get(url, params={"content": "true"}, timeout=20.0)
        resp.raise_for_status()
        payload = resp.json()

        results: list[CollectedJob] = []
        for item in payload.get("jobs", []):
            raw_html = item.get("content") or item.get("title") or ""
            description_clean = html_to_clean_text(raw_html)
            if not description_clean:
                continue

            location_obj = item.get("location") or {}
            location_raw = location_obj.get("name", "") if isinstance(location_obj, dict) else ""

            updated_at = item.get("updated_at")
            posted_at = datetime.fromisoformat(updated_at) if updated_at else None

            results.append(
                CollectedJob(
                    ats_source=ATSSource.GREENHOUSE,
                    external_id=str(item["id"]),
                    title=item["title"],
                    company_name=company_name,
                    apply_url=item["absolute_url"],
                    location_raw=location_raw,
                    raw_html=raw_html,
                    description_clean=description_clean,
                    posted_at=posted_at,
                )
            )

        logger.info("Greenhouse [%s]: fetched %d jobs", board_token, len(results))
        return results