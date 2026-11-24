from datetime import UTC, datetime
import logging


from stream_edge.collectors.base import (
    BaseATSCollector,
    CollectedJob,
    html_to_clean_text,
)
from vektryn_contracts import ATSSource

logger = logging.getLogger(__name__)


def _parse_dt(raw: str | int | float | None) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        ts = raw / 1000.0 if raw > 1e12 else float(raw)
        return datetime.fromtimestamp(ts, tz=UTC)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


class LeverCollector(BaseATSCollector):
    async def fetch_board(
        self, board_token: str, company_name: str
    ) -> list[CollectedJob]:
        resp = await self.http_client.get(
            f"https://api.lever.co/v0/postings/{board_token}",
            params={"mode": "json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            return []

        jobs: list[CollectedJob] = []
        for item in items:
            cats = item.get("categories") or {}
            loc_parts = [
                cats.get("location") or "",
                item.get("workplaceType") or "",
                *(cats.get("allLocations") or []),
            ]
            location_raw = ", ".join(dict.fromkeys(p for p in loc_parts if p))
            lists_html = "".join(
                f"<h4>{sec.get('text', '')}</h4>{sec.get('content', '')}"
                for sec in (item.get("lists") or [])
            )
            raw_html = f"{item.get('description', '')}\n{lists_html}\n{item.get('additional', '')}"
            apply_url = item.get("hostedUrl") or item.get("applyUrl")
            if not apply_url:
                continue
            jobs.append(
                CollectedJob(
                    ats_source=ATSSource.LEVER,
                    external_id=str(item["id"]),
                    title=(item.get("text") or "").strip(),
                    company_name=company_name,
                    apply_url=apply_url,
                    location_raw=location_raw,
                    raw_html=raw_html,
                    description_clean=item.get("descriptionPlain")
                    or html_to_clean_text(raw_html),
                    posted_at=_parse_dt(item.get("createdAt")),
                )
            )
        return jobs


class WorkableCollector(BaseATSCollector):
    async def fetch_board(
        self, board_token: str, company_name: str
    ) -> list[CollectedJob]:
        resp = await self.http_client.get(
            f"https://apply.workable.com/api/v1/widget/accounts/{board_token}",
            params={"details": "true"},
            timeout=15.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        resolved_company = (payload.get("name") or company_name).strip()
        jobs: list[CollectedJob] = []
        for item in payload.get("jobs") or []:
            loc_parts = [
                item.get("city") or "",
                item.get("state") or "",
                item.get("country") or "",
                "Remote" if item.get("telecommuting") else "",
            ]
            location_raw = ", ".join(p for p in loc_parts if p)
            raw_html = item.get("description") or ""
            apply_url = item.get("url") or item.get("application_url")
            if not apply_url:
                continue
            jobs.append(
                CollectedJob(
                    ats_source=ATSSource.WORKABLE,
                    external_id=str(item.get("shortcode") or apply_url[-40:]),
                    title=(item.get("title") or "").strip(),
                    company_name=resolved_company,
                    apply_url=apply_url,
                    location_raw=location_raw,
                    raw_html=raw_html,
                    description_clean=html_to_clean_text(raw_html),
                    posted_at=_parse_dt(item.get("published_on")),
                )
            )
        return jobs


class SmartRecruitersCollector(BaseATSCollector):
    async def fetch_board(
        self, board_token: str, company_name: str
    ) -> list[CollectedJob]:
        resp = await self.http_client.get(
            f"https://api.smartrecruiters.com/v1/companies/{board_token}/postings",
            params={"limit": 100},
            timeout=15.0,
        )
        resp.raise_for_status()
        jobs: list[CollectedJob] = []
        for item in resp.json().get("content") or []:
            posting_id = str(item["id"])
            company = ((item.get("company") or {}).get("name") or company_name).strip()
            loc = item.get("location") or {}
            loc_parts = [
                loc.get("fullLocation") or "",
                loc.get("country") or "",
                "Remote" if loc.get("remote") else "",
            ]
            location_raw = ", ".join(dict.fromkeys(p for p in loc_parts if p))
            # Fetch detail payload for full job description
            detail_html = ""
            try:
                d_resp = await self.http_client.get(
                    f"https://api.smartrecruiters.com/v1/companies/{board_token}/postings/{posting_id}",
                    timeout=10.0,
                )
                if d_resp.status_code == 200:
                    sections = (d_resp.json().get("jobAd") or {}).get("sections") or {}
                    detail_html = "\n".join(
                        sec.get("text", "")
                        for sec in sections.values()
                        if isinstance(sec, dict)
                    )
            except Exception:
                pass

            apply_url = f"https://jobs.smartrecruiters.com/{board_token}/{posting_id}"
            jobs.append(
                CollectedJob(
                    ats_source=ATSSource.SMARTRECRUITERS,
                    external_id=posting_id,
                    title=(item.get("name") or "").strip(),
                    company_name=company,
                    apply_url=apply_url,
                    location_raw=location_raw,
                    raw_html=detail_html or item.get("name", ""),
                    description_clean=html_to_clean_text(detail_html)
                    or item.get("name", ""),
                    posted_at=_parse_dt(item.get("releasedDate")),
                )
            )
        return jobs


class RecruiteeCollector(BaseATSCollector):
    async def fetch_board(
        self, board_token: str, company_name: str
    ) -> list[CollectedJob]:
        resp = await self.http_client.get(
            f"https://{board_token}.recruitee.com/api/offers/",
            timeout=15.0,
        )
        resp.raise_for_status()
        jobs: list[CollectedJob] = []
        for item in resp.json().get("offers") or []:
            apply_url = item.get("careers_url") or item.get("careers_apply_url")
            if not apply_url:
                continue
            loc_parts = [
                item.get("location") or "",
                item.get("country") or "",
                "Remote" if item.get("remote") else "",
            ]
            raw_html = f"{item.get('description', '')}\n{item.get('requirements', '')}"
            jobs.append(
                CollectedJob(
                    ats_source=ATSSource.RECRUITEE,
                    external_id=str(item["id"]),
                    title=(item.get("title") or "").strip(),
                    company_name=(item.get("company_name") or company_name).strip(),
                    apply_url=apply_url,
                    location_raw=", ".join(p for p in loc_parts if p),
                    raw_html=raw_html,
                    description_clean=html_to_clean_text(raw_html),
                    posted_at=_parse_dt(
                        item.get("published_at") or item.get("created_at")
                    ),
                )
            )
        return jobs


class BreezyCollector(BaseATSCollector):
    async def fetch_board(
        self, board_token: str, company_name: str
    ) -> list[CollectedJob]:
        resp = await self.http_client.get(
            f"https://{board_token}.breezy.hr/json",
            timeout=15.0,
        )
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            return []
        jobs: list[CollectedJob] = []
        for item in items:
            apply_url = item.get("url")
            if not apply_url:
                continue
            loc = item.get("location") or {}
            loc_name = loc.get("name") or ("Remote" if loc.get("is_remote") else "")
            company = ((item.get("company") or {}).get("name") or company_name).strip()
            jobs.append(
                CollectedJob(
                    ats_source=ATSSource.BREEZY,
                    external_id=str(item["id"]),
                    title=(item.get("name") or "").strip(),
                    company_name=company,
                    apply_url=apply_url,
                    location_raw=loc_name,
                    raw_html=item.get("name") or "",
                    description_clean=f"{item.get('name', '')} - {loc_name}",
                    posted_at=_parse_dt(item.get("published_date")),
                )
            )
        return jobs


class InHireCollector(BaseATSCollector):
    """Brazilian startup/scale-up ATS using public X-Tenant career endpoint."""

    async def fetch_board(
        self, board_token: str, company_name: str
    ) -> list[CollectedJob]:
        resp = await self.http_client.get(
            "https://api.inhire.app/job-posts/public/pages",
            headers={"X-Tenant": board_token, "Accept": "application/json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, dict) or not payload.get("jobsPage"):
            return []

        resolved_company = (payload.get("tenantName") or company_name).strip()
        jobs: list[CollectedJob] = []
        for item in payload.get("jobsPage") or []:
            job_id = str(item.get("jobId") or item.get("id") or "")
            if not job_id:
                continue
            workplace = item.get("workplaceType") or ""
            loc = item.get("location") or ""
            location_raw = ", ".join(p for p in (loc, workplace, "Brazil") if p)
            raw_html = item.get("description") or item.get("displayName") or ""
            apply_url = f"https://{board_token}.inhire.app/vagas/{job_id}"
            jobs.append(
                CollectedJob(
                    ats_source=ATSSource.INHIRE,
                    external_id=job_id,
                    title=(item.get("displayName") or "").strip(),
                    company_name=resolved_company,
                    apply_url=apply_url,
                    location_raw=location_raw,
                    raw_html=raw_html,
                    description_clean=html_to_clean_text(raw_html),
                    posted_at=_parse_dt(
                        item.get("createdAt") or item.get("publishedAt")
                    ),
                )
            )
        return jobs
