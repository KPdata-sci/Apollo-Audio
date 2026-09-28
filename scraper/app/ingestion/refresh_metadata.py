"""Cheap, metadata-only refresh for existing tracks — updates
playback_count/likes_count/artwork_url without a full rescrape (see
pipeline.py::refresh_track_metadata and docs/SCALING.md's "Popularity data
goes stale between scrapes"). A fixed-size batch per run
(APOLLO_METADATA_REFRESH_BATCH), oldest-refreshed-first, so a frequent
CronJob run stays quick and the whole table cycles through gradually.

Run locally (docker-compose):
    docker compose run --rm api python -m app.ingestion.refresh_metadata

Run in Kubernetes: infra/terraform-k8s/refresh-metadata-cronjob.tf runs this
on a schedule using the same `api` image, same warehouse DSN secret as the
api Deployment and the ingest CronJob.

One track's page yielding nothing (removed, blocked, moved) doesn't abort the
batch — it's logged and the next track still runs, same as ingest.py does
for one bad URL.
"""
import asyncio
import logging

from ..logging_config import configure_logging
from ..settings import settings
from ..warehouse import tracks_due_for_metadata_refresh
from .pipeline import DisallowedHostError, FetchError, refresh_track_metadata

configure_logging()
logger = logging.getLogger("apollo.refresh_metadata")

# Be courteous — sequential, paced, same ethos as playlists.py's own
# re-verify snippet and docs/CRAWLER_DESIGN.md, not a burst of concurrent
# requests against SoundCloud.
_PACE_SECONDS = 4.0


async def run() -> int:
    urls = tracks_due_for_metadata_refresh(settings.metadata_refresh_batch)
    if not urls:
        logger.info("No tracks to refresh (empty warehouse).")
        return 0

    logger.info("Refreshing metadata for %d track(s)", len(urls))
    refreshed = 0
    for i, url in enumerate(urls):
        try:
            if await refresh_track_metadata(url):
                refreshed += 1
                logger.info("Refreshed %s", url)
            else:
                logger.warning("No hydration data for %s — page removed/blocked/moved, skipped", url)
        except DisallowedHostError:
            logger.error("Skipping %s — not a soundcloud.com URL", url)
        except FetchError as exc:
            logger.error("Failed to fetch %s: %s", url, exc)
        except Exception:  # noqa: BLE001 - one bad track shouldn't kill the batch
            logger.exception("Unexpected error refreshing %s", url)
        if i < len(urls) - 1:
            await asyncio.sleep(_PACE_SECONDS)

    logger.info("Metadata refresh complete: %d/%d refreshed", refreshed, len(urls))
    # Unlike ingest.py, a track yielding nothing here is routine (SoundCloud
    # content just churns over time) rather than a sign something's actually
    # wrong with a configured source — so this always exits 0 rather than
    # flagging the k8s CronJob as Failed for what's an expected outcome.
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
