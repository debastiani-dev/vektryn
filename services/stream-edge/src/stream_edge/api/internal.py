import asyncio
import logging
import sys

from fastapi import APIRouter, Depends, HTTPException, Request, status

from stream_edge.api.ingest import verify_ingest_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _is_process_running(proc: asyncio.subprocess.Process | None) -> bool:
    return proc is not None and proc.returncode is None


@router.post(
    "/collect",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_ingest_api_key)],
)
async def trigger_local_collect(request: Request) -> dict[str, str | int]:
    """Spawns collectors in an isolated subprocess for local dev manual triggers."""
    active_proc: asyncio.subprocess.Process | None = getattr(
        request.app.state, "active_collect_proc", None
    )
    if _is_process_running(active_proc):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A collector sync run is already in progress.",
        )

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "stream_edge.collectors.run",
    )
    request.app.state.active_collect_proc = proc
    logger.info("Spawned local collector subprocess pid=%s", proc.pid)
    return {"status": "queued", "pid": proc.pid}
