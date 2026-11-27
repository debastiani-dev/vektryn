import asyncio
from datetime import datetime, timezone
import logging
import time

import httpx

from stream_edge.collectors.base import CollectedJob, html_to_clean_text
from vektryn_contracts.enums import ATSSource

logger = logging.getLogger(__name__)


def _parse_iso_dt(raw: str | int | float | None) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _trampos_company_name(item: dict) -> str:
    company_obj = item.get("company")
    if isinstance(company_obj, dict) and company_obj.get("name"):
        return str(company_obj["name"]).strip()
    return str(item.get("company_name") or "Trampos Company").strip()


def _trampos_location(item: dict) -> str:
    parts = [p for p in (item.get("city"), item.get("state"), "Brazil") if p]
    if item.get("home_office") or item.get("remote"):
        parts.append("Remote")
    return ", ".join(str(p) for p in parts)


def _parse_trampos_entry(entry: object) -> CollectedJob | None:
    if not isinstance(entry, dict):
        return None
    item = entry.get("opportunity", entry)
    if not isinstance(item, dict):
        return None
    opp_id = str(item.get("id") or item.get("slug") or "")
    title = str(item.get("name") or item.get("title") or "").strip()
    if not opp_id or not title:
        return None

    permalink = item.get("permalink") or f"https://trampos.co/oportunidades/{opp_id}"
    raw_html = str(item.get("description") or item.get("name") or "")
    posted_raw = item.get("published_at") or item.get("created_at")

    return CollectedJob(
        ats_source=ATSSource.TRAMPOS,
        external_id=opp_id,
        title=title,
        company_name=_trampos_company_name(item),
        apply_url=permalink,
        location_raw=_trampos_location(item),
        raw_html=raw_html,
        description_clean=html_to_clean_text(raw_html),
        posted_at=_parse_iso_dt(posted_raw),
    )


class MultiCompanyFeedCollector:
    """Fetches remote and Brazilian software, UI/UX, and QA jobs from public multi-company JSON feeds."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def fetch_remotive(
        self, category: str = "software-dev"
    ) -> list[CollectedJob]:
        resp = await self.http_client.get(
            "https://remotive.com/api/remote-jobs",
            params={"category": category, "limit": 100},
            timeout=20.0,
        )
        resp.raise_for_status()
        jobs: list[CollectedJob] = []
        for item in resp.json().get("jobs", []):
            raw_html = item.get("description") or ""
            jobs.append(
                CollectedJob(
                    ats_source=ATSSource.REMOTIVE,
                    external_id=str(item["id"]),
                    title=(item.get("title") or "").strip(),
                    company_name=(
                        item.get("company_name") or "Remotive Company"
                    ).strip(),
                    apply_url=item.get("url") or "",
                    location_raw=(
                        item.get("candidate_required_location") or "Worldwide"
                    ).strip(),
                    raw_html=raw_html,
                    description_clean=html_to_clean_text(raw_html),
                    posted_at=_parse_iso_dt(item.get("publication_date")),
                )
            )
        return [j for j in jobs if j.apply_url and j.title]

    async def fetch_himalayas(self, limit: int = 100) -> list[CollectedJob]:
        resp = await self.http_client.get(
            "https://himalayas.app/jobs/api",
            params={"limit": limit},
            timeout=20.0,
        )
        resp.raise_for_status()
        jobs: list[CollectedJob] = []
        for item in resp.json().get("jobs", []):
            raw_html = item.get("description") or item.get("excerpt") or ""
            loc_restrictions = item.get("locationRestrictions") or []
            location_raw = ", ".join(loc_restrictions) if loc_restrictions else "Remote"
            apply_url = item.get("applicationLink") or item.get("guid") or ""
            ext_id = str(item.get("id") or item.get("guid") or apply_url[-40:])
            jobs.append(
                CollectedJob(
                    ats_source=(
                        ATSSource.HIMALAS
                        if hasattr(ATSSource, "HIMALAS")
                        else ATSSource.HIMALAYAS
                    ),
                    external_id=ext_id,
                    title=(item.get("title") or "").strip(),
                    company_name=(
                        item.get("companyName") or "Himalayas Company"
                    ).strip(),
                    apply_url=apply_url,
                    location_raw=location_raw,
                    raw_html=raw_html,
                    description_clean=html_to_clean_text(raw_html),
                    posted_at=_parse_iso_dt(item.get("pubDate")),
                )
            )
        return [j for j in jobs if j.apply_url and j.title]

    async def fetch_jobicy(self, tag: str = "python") -> list[CollectedJob]:
        resp = await self.http_client.get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": 50, "tag": tag},
            timeout=20.0,
        )
        resp.raise_for_status()
        jobs: list[CollectedJob] = []
        for item in resp.json().get("jobs", []):
            raw_html = item.get("jobDescription") or item.get("jobExcerpt") or ""
            jobs.append(
                CollectedJob(
                    ats_source=ATSSource.JOBICY,
                    external_id=str(item["id"]),
                    title=(item.get("jobTitle") or "").strip(),
                    company_name=(item.get("companyName") or "Jobicy Company").strip(),
                    apply_url=item.get("url") or "",
                    location_raw=(item.get("jobGeo") or "Anywhere").strip(),
                    raw_html=raw_html,
                    description_clean=html_to_clean_text(raw_html),
                    posted_at=_parse_iso_dt(item.get("pubDate")),
                )
            )
        return [j for j in jobs if j.apply_url and j.title]

    @staticmethod
    def _parse_gupy_item(item: dict) -> CollectedJob | None:
        job_id = str(item.get("id") or "")
        apply_url = item.get("jobUrl") or ""
        title = (item.get("name") or "").strip()
        if not apply_url or not job_id or not title:
            return None
        workplace_type = str(item.get("workplaceType") or "").strip()
        if not workplace_type and item.get("isRemoteWork"):
            workplace_type = "Remote"
        loc_parts = [
            item.get("city") or "",
            item.get("state") or "",
            item.get("country") or "Brazil",
            workplace_type,
        ]
        raw_html = item.get("description") or title
        return CollectedJob(
            ats_source=ATSSource.GUPY,
            external_id=job_id,
            title=title,
            company_name=(item.get("careerPageName") or "Gupy Company").strip(),
            apply_url=apply_url,
            location_raw=", ".join(dict.fromkeys(p for p in loc_parts if p)),
            raw_html=raw_html,
            description_clean=html_to_clean_text(raw_html),
            posted_at=_parse_iso_dt(item.get("publishedDate")),
            work_mode_hint=workplace_type,
        )

    async def fetch_gupy_portal(self, job_name: str = "python") -> list[CollectedJob]:
        resp = await self.http_client.get(
            "https://portal.gupy.io/api/job-search/jobs",
            params={"jobName": job_name, "limit": 50, "offset": 0},
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=20.0,
        )
        resp.raise_for_status()
        parsed = (self._parse_gupy_item(item) for item in resp.json().get("data", []))
        return [job for job in parsed if job is not None]

    async def fetch_trampos(self) -> list[CollectedJob]:
        resp = await self.http_client.get(
            "https://trampos.co/api/v2/opportunities.json",
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=20.0,
        )
        resp.raise_for_status()
        payload = resp.json()
        items = (
            payload if isinstance(payload, list) else payload.get("opportunities", [])
        )
        parsed = (_parse_trampos_entry(entry) for entry in items)
        return [job for job in parsed if job is not None]

    async def fetch_github_vagas(self, repo: str) -> list[CollectedJob]:
        resp = await self.http_client.get(
            f"https://api.github.com/repos/{repo}/issues",
            params={"state": "open", "per_page": 60},
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "vektryn-collector",
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        jobs: list[CollectedJob] = []
        for issue in resp.json():
            if "pull_request" in issue:
                continue
            issue_num = str(issue.get("number") or issue.get("id") or "")
            html_url = issue.get("html_url") or ""
            title = (issue.get("title") or "").strip()
            body = issue.get("body") or ""
            labels = [
                lbl.get("name", "")
                for lbl in (issue.get("labels") or [])
                if isinstance(lbl, dict)
            ]
            location_raw = ", ".join(labels) if labels else "Brazil, Remote"
            jobs.append(
                CollectedJob(
                    ats_source=ATSSource.GITHUB_VAGAS,
                    external_id=f"{repo}#{issue_num}",
                    title=title,
                    company_name=repo,
                    apply_url=html_url,
                    location_raw=location_raw,
                    raw_html=body,
                    description_clean=html_to_clean_text(body),
                    posted_at=_parse_iso_dt(issue.get("created_at")),
                )
            )
        return [j for j in jobs if j.apply_url and j.title]

    async def fetch_all_with_stats(
        self,
    ) -> tuple[list[CollectedJob], dict[str, dict[str, int]]]:
        feed_calls = (
            ("remotive", ATSSource.REMOTIVE.value, self.fetch_remotive("software-dev")),
            (
                "remotive:design",
                ATSSource.REMOTIVE.value,
                self.fetch_remotive("design"),
            ),
            ("remotive:qa", ATSSource.REMOTIVE.value, self.fetch_remotive("qa")),
            ("himalayas", ATSSource.HIMALAYAS.value, self.fetch_himalayas(limit=100)),
            ("jobicy:python", ATSSource.JOBICY.value, self.fetch_jobicy("python")),
            ("jobicy:backend", ATSSource.JOBICY.value, self.fetch_jobicy("backend")),
            ("jobicy:design", ATSSource.JOBICY.value, self.fetch_jobicy("design")),
            ("jobicy:qa", ATSSource.JOBICY.value, self.fetch_jobicy("qa")),
            ("gupy:python", ATSSource.GUPY.value, self.fetch_gupy_portal("python")),
            ("gupy:backend", ATSSource.GUPY.value, self.fetch_gupy_portal("backend")),
            ("gupy:ux", ATSSource.GUPY.value, self.fetch_gupy_portal("ux")),
            ("gupy:designer", ATSSource.GUPY.value, self.fetch_gupy_portal("designer")),
            ("gupy:qa", ATSSource.GUPY.value, self.fetch_gupy_portal("qa")),
            ("trampos", ATSSource.TRAMPOS.value, self.fetch_trampos()),
            (
                "github:backend-br",
                ATSSource.GITHUB_VAGAS.value,
                self.fetch_github_vagas("backend-br/vagas"),
            ),
        )

        async def _timed_fetch(coro):
            started = time.perf_counter()
            try:
                return await coro, int((time.perf_counter() - started) * 1000), None
            except Exception as exc:
                return None, int((time.perf_counter() - started) * 1000), exc

        results = await asyncio.gather(
            *(_timed_fetch(coro) for _, _, coro in feed_calls)
        )

        merged: list[CollectedJob] = []
        seen_urls: set[str] = set()
        stats: dict[str, dict[str, int]] = {}

        for (label, source_key, _), (jobs, elapsed_ms, exc) in zip(
            feed_calls, results, strict=True
        ):
            entry = stats.setdefault(
                source_key, {"fetched": 0, "errors": 0, "duration_ms": 0}
            )
            entry["duration_ms"] = max(entry["duration_ms"], elapsed_ms)
            if exc is not None:
                entry["errors"] += 1
                logger.warning("Feed[%s] failed: %s", label, exc)
                continue
            added = 0
            for job in jobs or []:
                if job.apply_url in seen_urls:
                    continue
                seen_urls.add(job.apply_url)
                merged.append(job)
                added += 1
            entry["fetched"] += added
            logger.info("Feed[%s]: fetched %d new postings", label, added)

        return merged, stats

    async def fetch_all(self) -> list[CollectedJob]:
        jobs, _ = await self.fetch_all_with_stats()
        return jobs
