import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .settings import settings

logger = logging.getLogger("apollo.lake")


def _object_key(source_url: str, scraped_at: datetime) -> str:
    host_path = urlparse(source_url).path.strip("/").replace("/", "_") or "root"
    stamp = scraped_at.strftime("%Y/%m/%d/%H%M%S")
    return f"raw/soundcloud/{stamp}_{host_path}.json"


class FilesystemLake:
    """Local bind-mounted directory acting as the data lake. Same object-key
    layout as the S3 backend, so switching to real S3/MinIO later is just a
    config change (APOLLO_LAKE_BACKEND=s3), not a rewrite of calling code."""

    def __init__(self, root: str):
        self.root = Path(root)

    def ensure_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, payload: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


class S3Lake:
    """MinIO / real-S3 backend, used when APOLLO_LAKE_BACKEND=s3."""

    def __init__(self):
        import boto3  # imported lazily so boto3 isn't required for the filesystem-only path

        self._bucket = settings.s3_lake_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )

    def ensure_ready(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def put(self, key: str, payload: bytes) -> None:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=payload, ContentType="application/json"
        )


def _build_lake():
    if settings.lake_backend == "s3":
        return S3Lake()
    return FilesystemLake(settings.lake_path)


_lake = _build_lake()


def ensure_bucket() -> None:
    _lake.ensure_ready()


def put_raw_scrape(source_url: str, tracks: list[dict], scraped_at: datetime | None = None) -> str:
    """Land an immutable, timestamped raw scrape in the data lake before any
    transformation happens. The warehouse loader reads from here rather than
    from the live scrape, so the raw payload is always recoverable/replayable."""
    scraped_at = scraped_at or datetime.now(timezone.utc)
    key = _object_key(source_url, scraped_at)

    payload = {
        "source_url": source_url,
        "scraped_at": scraped_at.isoformat(),
        "track_count": len(tracks),
        "tracks": tracks,
    }

    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    _lake.put(key, body)
    logger.debug("Wrote %d bytes to lake key %s (backend=%s)", len(body), key, settings.lake_backend)
    return key
