from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Data lake. "filesystem" writes to a bind-mounted local directory (default —
    # works with no extra container). "s3" talks to MinIO/real S3 via boto3;
    # switch to it by setting APOLLO_LAKE_BACKEND=s3 once you have an S3-compatible
    # endpoint available (this repo's docker-compose doesn't run one by default,
    # see infra notes in the README).
    lake_backend: str = "filesystem"
    lake_path: str = "/data/lake"

    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_lake_bucket: str = "soundcloud-lake"
    s3_region: str = "us-east-1"

    # Data warehouse (Postgres)
    warehouse_dsn: str = "postgresql://apollo:apollo@postgres:5432/apollo"

    # Scraper behaviour
    scrape_timeout_ms: int = 15000
    max_scroll_iterations: int = 40
    scroll_pause_ms: int = 1000

    # Optional, for pages that require being logged in as a specific SoundCloud
    # account (e.g. a personal "Discover Weekly"). Never set by this codebase —
    # you obtain this yourself from your own browser (DevTools -> Application ->
    # Cookies, after logging in) and paste it into your own .env. This project
    # never asks for or stores your SoundCloud password. Untested against a real
    # login wall (no test account was available while building this).
    soundcloud_cookies: str = ""

    # Standalone-API deployment. When set, POST /scrape and POST
    # /api/discover-playlists require a matching `X-API-Key` header (GET
    # endpoints stay open either way). Empty (the default, and what
    # docker-compose's local dev setup uses) means those endpoints are
    # unauthenticated, same as before this setting existed. Set via
    # APOLLO_API_KEY — never commit a real value.
    api_key: str = ""

    # Comma-separated list of origins allowed to call this API cross-origin
    # (needed once the front end is served from a different origin than the
    # API — see frontend/). "*" (default) allows any origin, which is fine for
    # the GET endpoints but means don't rely on cookies/session auth here.
    cors_origins: str = "*"

    # Logging
    log_level: str = "INFO"
    log_dir: str = "/var/log/apollo"
    log_max_bytes: int = 5_000_000  # rotate apollo.log once it exceeds this size
    log_backup_count: int = 10      # how many rotated (and gzipped) files to keep

    class Config:
        env_prefix = "APOLLO_"


settings = Settings()
