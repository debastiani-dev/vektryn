import asyncio
from pathlib import Path

from google.cloud import storage

from stream_edge.config import settings


class SnapshotStorageClient:
    def __init__(
        self,
        bucket_name: str = settings.gcs_bucket_name,
        local_dir: Path = settings.local_storage_dir,
    ) -> None:
        self.bucket_name = bucket_name.strip()
        self.local_dir = local_dir
        self._gcs_client: storage.Client | None = None

    @property
    def gcs_client(self) -> storage.Client:
        if self._gcs_client is None:
            self._gcs_client = storage.Client()
        return self._gcs_client

    def _save_sync(self, object_path: str, raw_html: str) -> str:
        if self.bucket_name:
            bucket = self.gcs_client.bucket(self.bucket_name)
            blob = bucket.blob(object_path)
            blob.upload_from_string(raw_html, content_type="text/html; charset=utf-8")
            return f"gs://{self.bucket_name}/{object_path}"

        target_path = self.local_dir / object_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(raw_html, encoding="utf-8")
        return target_path.resolve().as_uri()

    async def save_raw_html(
        self,
        *,
        ats_source: str,
        external_id: str,
        content_hash: str,
        raw_html: str,
    ) -> str:
        safe_id = external_id.replace("/", "_")
        object_path = f"raw_html/{ats_source}/{safe_id}_{content_hash[:12]}.html"
        return await asyncio.to_thread(self._save_sync, object_path, raw_html)
