"""Standalone entrypoint for scheduled ingestion — the same fetch -> parse ->
lake -> warehouse pipeline as POST /scrape (see pipeline.py), run against a
fixed list of URLs (APOLLO_INGEST_URLS) instead of one ad-hoc request.

Run locally (docker-compose):
    docker compose run --rm api python -m app.ingest

Run in Kubernetes: infra/terraform-k8s/ingest-cronjob.tf runs this on a
schedule using the same `api` image, with APOLLO_INGEST_URLS/warehouse DSN
from the same secret the api Deployment uses and the same data-lake PVC
mounted, so ingested tracks land in exactly the same place a manual scrape
would.

One bad/blocked URL doesn't abort the batch — it's logged and the next URL
in the list still runs.
"""
import asyncio
import logging

from .logging_config import configure_logging
from .pipeline import (
    DisallowedHostError,
    FetchError,
    LakeWriteError,
    LoginRequiredError,
    scrape_and_store,
)
from .settings import settings

configure_logging()
logger = logging.getLogger("apollo.ingest")


async def run() -> int:
    urls = settings.ingest_urls_list()
    if not urls:
        logger.warning(
            "APOLLO_INGEST_URLS is empty — nothing to ingest. Set it to a "
            "comma-separated list of soundcloud.com playlist/profile URLs."
        )
        return 0

    logger.info("Starting scheduled ingest of %d URL(s)", len(urls))
    succeeded = 0
    for url in urls:
        try:
            result = await scrape_and_store(url)
            logger.info(
                "Ingested %d track(s) from %s -> %s",
                result["track_count"], url, result["lake_object_key"],
            )
            succeeded += 1
        except DisallowedHostError:
            logger.error("Skipping %s — not a soundcloud.com URL", url)
        except LoginRequiredError:
            logger.error(
                "Skipping %s — SoundCloud says this requires being logged in "
                "as its owner (set APOLLO_SOUNDCLOUD_COOKIES if this is your own account)",
                url,
            )
        except FetchError as exc:
            logger.error("Failed to fetch %s: %s", url, exc)
        except LakeWriteError as exc:
            logger.error("Failed to write %s to the data lake: %s", url, exc)
        except Exception:  # noqa: BLE001 - one bad URL shouldn't kill the batch
            logger.exception("Unexpected error ingesting %s", url)

    logger.info("Scheduled ingest complete: %d/%d succeeded", succeeded, len(urls))
    return 0 if succeeded == len(urls) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
