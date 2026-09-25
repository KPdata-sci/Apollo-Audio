import asyncio
from unittest.mock import AsyncMock, patch

from app import ingest


@patch("app.ingest.settings")
@patch("app.ingest.scrape_and_store", new_callable=AsyncMock)
def test_run_ingests_every_configured_url(mock_scrape, mock_settings):
    mock_settings.ingest_urls_list.return_value = [
        "https://soundcloud.com/a/sets/one",
        "https://soundcloud.com/b/sets/two",
    ]
    mock_scrape.return_value = {"track_count": 3, "lake_object_key": "raw/soundcloud/fake.json"}

    exit_code = asyncio.run(ingest.run())

    assert exit_code == 0
    assert mock_scrape.call_count == 2
    mock_scrape.assert_any_call("https://soundcloud.com/a/sets/one")
    mock_scrape.assert_any_call("https://soundcloud.com/b/sets/two")


@patch("app.ingest.settings")
@patch("app.ingest.scrape_and_store", new_callable=AsyncMock)
def test_run_continues_past_a_failing_url(mock_scrape, mock_settings):
    mock_settings.ingest_urls_list.return_value = [
        "https://soundcloud.com/bad/sets/one",
        "https://soundcloud.com/good/sets/two",
    ]
    mock_scrape.side_effect = [
        ingest.FetchError("boom"),
        {"track_count": 5, "lake_object_key": "raw/soundcloud/fake2.json"},
    ]

    exit_code = asyncio.run(ingest.run())

    # One of two failed — non-zero exit so a k8s CronJob run shows as Failed,
    # but both URLs were still attempted rather than aborting the batch.
    assert exit_code == 1
    assert mock_scrape.call_count == 2


@patch("app.ingest.settings")
@patch("app.ingest.scrape_and_store", new_callable=AsyncMock)
def test_run_is_a_noop_when_no_urls_configured(mock_scrape, mock_settings):
    mock_settings.ingest_urls_list.return_value = []

    exit_code = asyncio.run(ingest.run())

    assert exit_code == 0
    mock_scrape.assert_not_called()
