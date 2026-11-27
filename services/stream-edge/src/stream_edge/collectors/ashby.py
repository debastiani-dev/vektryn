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
            workplace_type = str(item.get("workplaceType") or "").strip()
            if not workplace_type and item.get("isRemote") is True:
                workplace_type = "Remote"
            raw_location = str(item.get("location") or "").strip()
            loc_parts = [raw_location]
            if workplace_type and workplace_type.lower() not in raw_location.lower():
                loc_parts.append(workplace_type)
            location_raw = ", ".join(p for p in loc_parts if p)

            results.append(
                CollectedJob(
                    ats_source=ATSSource.ASHBY,
                    external_id=str(item["id"]),
                    title=item["title"],
                    company_name=company_name,
                    apply_url=item["jobUrl"],
                    location_raw=location_raw,
                    raw_html=raw_html,
                    description_clean=description_clean,
                    posted_at=posted_at,
                    work_mode_hint=workplace_type,
                )
            )

        logger.info("Ashby [%s]: fetched %d jobs", board_token, len(results))
        return results
