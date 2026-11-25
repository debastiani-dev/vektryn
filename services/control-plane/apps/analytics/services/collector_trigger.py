import logging
from typing import Any

from django.conf import settings
import httpx
import redis

logger = logging.getLogger(__name__)

COLLECT_COOLDOWN_KEY = "vektryn:system:collect_cooldown"
COLLECT_COOLDOWN_SECONDS = 300
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/token"
)


class CollectCooldownError(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(
            f"Collector sync is on cooldown. Retry in {self.retry_after}s."
        )


class CollectTriggerError(Exception):
    """Raised when the upstream Cloud Run Job or local collector trigger fails."""


def _get_redis_client() -> redis.Redis | None:
    redis_url = (getattr(settings, "REDIS_URL", "") or "").strip()
    if not redis_url:
        return None
    try:
        return redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
    except Exception as exc:
        logger.debug("Redis unavailable for collector cooldown: %s", exc)
        return None


def get_collect_cooldown_remaining() -> int:
    client = _get_redis_client()
    if client is None:
        return 0
    try:
        ttl = client.ttl(COLLECT_COOLDOWN_KEY)
        return max(0, int(ttl)) if isinstance(ttl, int) and ttl > 0 else 0
    except Exception as exc:
        logger.debug("Failed checking collector cooldown TTL: %s", exc)
        return 0


def _acquire_collect_cooldown() -> bool:
    """Atomically claims the 5-minute cooldown lock via SET NX EX."""
    client = _get_redis_client()
    if client is None:
        return False
    try:
        acquired = client.set(
            COLLECT_COOLDOWN_KEY,
            "1",
            nx=True,
            ex=COLLECT_COOLDOWN_SECONDS,
        )
        if not acquired:
            ttl = client.ttl(COLLECT_COOLDOWN_KEY)
            retry_after = (
                int(ttl)
                if isinstance(ttl, int) and ttl > 0
                else COLLECT_COOLDOWN_SECONDS
            )
            raise CollectCooldownError(retry_after=retry_after)
        return True
    except CollectCooldownError:
        raise
    except Exception as exc:
        logger.warning("Redis collector cooldown acquisition failed: %s", exc)
        return False


def _release_collect_cooldown() -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.delete(COLLECT_COOLDOWN_KEY)
    except Exception as exc:
        logger.debug("Failed releasing collector cooldown lock: %s", exc)


def _fetch_gcp_metadata_token() -> str:
    try:
        resp = httpx.get(
            METADATA_TOKEN_URL,
            headers={"Metadata-Flavor": "Google"},
            timeout=3.0,
        )
        resp.raise_for_status()
        token = str(resp.json().get("access_token") or "").strip()
    except Exception as exc:
        raise CollectTriggerError(
            f"Unable to fetch GCP metadata access token: {exc}"
        ) from exc
    if not token:
        raise CollectTriggerError("GCP metadata server returned an empty access token.")
    return token


def _trigger_cloud_run_job(
    *,
    project_id: str,
    region: str,
    job_name: str,
) -> dict[str, Any]:
    token = _fetch_gcp_metadata_token()
    url = (
        f"https://run.googleapis.com/v2/projects/{project_id}"
        f"/locations/{region}/jobs/{job_name}:run"
    )
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={},
            timeout=10.0,
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
    except httpx.HTTPError as exc:
        raise CollectTriggerError(
            f"Cloud Run Job {job_name} trigger failed: {exc}"
        ) from exc

    execution_id = str(
        payload.get("name") or payload.get("metadata", {}).get("name") or ""
    )
    return {
        "status": "queued",
        "mode": "cloud_run_job",
        "job_name": job_name,
        "execution_id": execution_id or None,
        "cooldown_seconds": COLLECT_COOLDOWN_SECONDS,
    }


def _trigger_local_stream_edge(
    *,
    stream_edge_url: str,
    ingest_api_key: str,
) -> dict[str, Any]:
    endpoint = f"{stream_edge_url.rstrip('/')}/internal/collect"
    headers = {"X-Ingest-API-Key": ingest_api_key} if ingest_api_key else {}
    try:
        resp = httpx.post(endpoint, headers=headers, json={}, timeout=10.0)
        if resp.status_code == 409:
            raise CollectCooldownError(retry_after=60)
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
    except CollectCooldownError:
        raise
    except httpx.HTTPError as exc:
        raise CollectTriggerError(
            f"Local Stream Edge collector trigger failed: {exc}"
        ) from exc

    return {
        "status": "queued",
        "mode": "stream_edge_local",
        "job_name": "vektryn-collect",
        "execution_id": str(payload.get("pid") or "") or None,
        "cooldown_seconds": COLLECT_COOLDOWN_SECONDS,
    }


def trigger_collector_sync() -> dict[str, Any]:
    lock_acquired = _acquire_collect_cooldown()
    project_id = (getattr(settings, "GCP_PROJECT_ID", "") or "").strip()
    region = (getattr(settings, "GCP_REGION", "") or "us-central1").strip()
    job_name = (getattr(settings, "COLLECTOR_JOB_NAME", "") or "").strip()
    stream_edge_url = (getattr(settings, "STREAM_EDGE_URL", "") or "").strip()
    ingest_api_key = (getattr(settings, "INGEST_API_KEY", "") or "").strip()

    try:
        if project_id and job_name:
            return _trigger_cloud_run_job(
                project_id=project_id,
                region=region,
                job_name=job_name,
            )
        if stream_edge_url:
            return _trigger_local_stream_edge(
                stream_edge_url=stream_edge_url,
                ingest_api_key=ingest_api_key,
            )
        raise CollectTriggerError(
            "Collector trigger is not configured (set GCP_PROJECT_ID + COLLECTOR_JOB_NAME or STREAM_EDGE_URL)."
        )
    except CollectTriggerError:
        if lock_acquired:
            _release_collect_cooldown()
        raise
