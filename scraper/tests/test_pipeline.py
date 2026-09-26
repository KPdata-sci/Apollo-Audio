import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.pipeline import DisallowedHostError, refresh_track_metadata


@patch("app.pipeline.warehouse.update_track_metadata")
@patch("app.pipeline.fetch_track_metadata", new_callable=AsyncMock)
def test_refresh_track_metadata_updates_the_warehouse(mock_fetch, mock_update):
    mock_fetch.return_value = {"playback_count": 100, "likes_count": 10, "artwork_url": "https://i1.sndcdn.com/x.jpg"}

    result = asyncio.run(refresh_track_metadata("https://soundcloud.com/artist/track"))

    assert result is True
    mock_update.assert_called_once_with(
        "https://soundcloud.com/artist/track", playback_count=100, likes_count=10,
        artwork_url="https://i1.sndcdn.com/x.jpg",
    )


@patch("app.pipeline.warehouse.update_track_metadata")
@patch("app.pipeline.fetch_track_metadata", new_callable=AsyncMock)
def test_refresh_track_metadata_is_a_noop_when_nothing_comes_back(mock_fetch, mock_update):
    mock_fetch.return_value = None

    result = asyncio.run(refresh_track_metadata("https://soundcloud.com/artist/gone"))

    assert result is False
    mock_update.assert_not_called()


def test_refresh_track_metadata_rejects_non_soundcloud_url():
    with pytest.raises(DisallowedHostError):
        asyncio.run(refresh_track_metadata("http://169.254.169.254/latest/meta-data/"))
