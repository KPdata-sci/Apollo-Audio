import asyncio
from unittest.mock import AsyncMock, patch

from app.ingestion import refresh_metadata


@patch("app.ingestion.refresh_metadata.asyncio.sleep", new_callable=AsyncMock)
@patch("app.ingestion.refresh_metadata.tracks_due_for_metadata_refresh")
@patch("app.ingestion.refresh_metadata.refresh_track_metadata", new_callable=AsyncMock)
def test_run_refreshes_every_due_track(mock_refresh, mock_due, mock_sleep):
    mock_due.return_value = ["https://soundcloud.com/a/b", "https://soundcloud.com/c/d"]
    mock_refresh.return_value = True

    exit_code = asyncio.run(refresh_metadata.run())

    assert exit_code == 0
    assert mock_refresh.call_count == 2
    mock_refresh.assert_any_call("https://soundcloud.com/a/b")
    mock_refresh.assert_any_call("https://soundcloud.com/c/d")
    # Paced between tracks, but not after the last one.
    assert mock_sleep.call_count == 1


@patch("app.ingestion.refresh_metadata.asyncio.sleep", new_callable=AsyncMock)
@patch("app.ingestion.refresh_metadata.tracks_due_for_metadata_refresh")
@patch("app.ingestion.refresh_metadata.refresh_track_metadata", new_callable=AsyncMock)
def test_run_continues_past_a_track_with_nothing_to_refresh(mock_refresh, mock_due, mock_sleep):
    # A track whose page yields no hydration data (removed/blocked/moved) is
    # routine, not a failure — the batch still finishes and still exits 0.
    mock_due.return_value = ["https://soundcloud.com/gone/track", "https://soundcloud.com/ok/track"]
    mock_refresh.side_effect = [False, True]

    exit_code = asyncio.run(refresh_metadata.run())

    assert exit_code == 0
    assert mock_refresh.call_count == 2


@patch("app.ingestion.refresh_metadata.tracks_due_for_metadata_refresh", return_value=[])
@patch("app.ingestion.refresh_metadata.refresh_track_metadata", new_callable=AsyncMock)
def test_run_is_a_noop_when_nothing_is_due(mock_refresh, mock_due):
    exit_code = asyncio.run(refresh_metadata.run())

    assert exit_code == 0
    mock_refresh.assert_not_called()
