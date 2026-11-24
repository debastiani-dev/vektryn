import logging
from datetime import datetime

from stream_edge.collectors.base import (
    BaseATSCollector,
    CollectedJob,
    html_to_clean_text,
)
from vektryn_contracts import ATSSource

logger = logging.getLogger(__name__)


class AshbyCollector(BaseATSCollector):
    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"

    async def fetch_board(
        self, board_token: str, company_name: str
    ) -> list[CollectedJob]:
        url = f"{self.BASE_URL}/{board_token}"
        resp = await self.http_client.get(url, timeout=20.0)
        resp.raise_for_status()
        payload = resp.json()

        results: list[CollectedJob] = []
        for item in payload.get("jobs", []):
            if item.get("isListed") is False:
                continue

            raw_html = item.get("descriptionHtml") or item.get("descriptionPlain") or ""
            description_clean = html_to_clean_text(raw_html)
            if not description_clean:
                continue

            published_at = item.get("publishedAt")
            posted_at = datetime.fromisoformat(published_at) if published_at else None

            results.append(
                CollectedJob(
                    ats_source=ATSSource.ASHBY,
                    external_id=str(item["id"]),
                    title=item["title"],
                    company_name=company_name,
                    apply_url=item["jobUrl"],
                    location_raw=item.get("location", ""),
                    raw_html=raw_html,
                    description_clean=description_clean,
                    posted_at=posted_at,
                )
            )

        logger.info("Ashby [%s]: fetched %d jobs", board_token, len(results))
        return results
