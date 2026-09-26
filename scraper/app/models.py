from datetime import datetime

from pydantic import BaseModel, HttpUrl


class ScrapeRequest(BaseModel):
    url: HttpUrl


class DiscoverPlaylistsRequest(BaseModel):
    profile_url: HttpUrl


class Track(BaseModel):
    title: str
    artist: str
    genre: str | None = None
    url: str | None = None
    downloadable: bool = False
    playback_count: int | None = None
    likes_count: int | None = None
    artwork_url: str | None = None


class ScrapeResult(BaseModel):
    source_url: str
    scraped_at: datetime
    track_count: int
    lake_object_key: str
    tracks: list[Track]


class TrackRow(BaseModel):
    id: int
    artist: str
    title: str
    genre: str | None = None
    url: str | None = None
    downloadable: bool = False
    playback_count: int | None = None
    likes_count: int | None = None
    artwork_url: str | None = None
    favorited: bool = False
    source_url: str
    scraped_at: datetime


class TracksPage(BaseModel):
    items: list[TrackRow]
    total: int
    limit: int
    offset: int


class GenreCount(BaseModel):
    genre: str
    count: int


class SourceSummary(BaseModel):
    source_url: str
    track_count: int
    last_scraped_at: datetime


class WarehouseStats(BaseModel):
    total_tracks: int
    total_sources: int
    total_favorites: int
    last_scraped_at: datetime | None = None
    genres: list[GenreCount]
    sources: list[SourceSummary]


class FavoriteResult(BaseModel):
    id: int
    favorited: bool


class PlaylistEntry(BaseModel):
    name: str
    url: str
    note: str | None = None


class DiscoveredPlaylists(BaseModel):
    profile_url: str
    playlists: list[PlaylistEntry]
