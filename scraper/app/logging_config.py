import gzip
import logging
import logging.handlers
import shutil
from contextvars import ContextVar
from pathlib import Path

from .settings import settings

# Set per-request in main.py's logging middleware. Every log line emitted
# while handling a request — whether it comes from apollo.main, apollo.scraping,
# apollo.warehouse, or apollo.lake — carries the same id, so `grep <id>
# apollo.log` pulls the full story of one scrape (fetch -> parse -> lake write
# -> warehouse load) even though those steps log from different modules.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_base_record_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs) -> logging.LogRecord:
    """Stamps every LogRecord with the current request id as it's created —
    this runs for *all* loggers regardless of which one originated the record
    (unlike a Filter, which only fires for the exact logger it's attached to,
    not that logger's children — attaching it to the "apollo" logger looked
    right but silently never ran for "apollo.main"/"apollo.scraping"/etc.,
    which is what every actual log call in this app uses)."""
    record = _base_record_factory(*args, **kwargs)
    record.request_id = request_id_var.get()
    return record


_GZIP_MAGIC = b"\x1f\x8b"


def _gzip_and_remove(source: str, dest: str) -> None:
    """Rotator hook for RotatingFileHandler: instead of just renaming the
    rotated-out file (the default), gzip it — so old logs take a fraction of
    the space once you're past a handful of rotations.

    With backupCount > 1, RotatingFileHandler also uses this same rotator to
    shift existing backups down a slot (e.g. apollo.log.2.gz -> .3.gz) — those
    are already compressed, so gzipping them again would silently nest another
    gzip layer on every rotation (9 layers deep by backup #10). Detect that via
    the gzip magic bytes and just move the file instead."""
    with open(source, "rb") as f:
        already_gzipped = f.read(2) == _GZIP_MAGIC

    if already_gzipped:
        shutil.move(source, dest)
        return

    with open(source, "rb") as f_in, gzip.open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    Path(source).unlink()


def configure_logging() -> None:
    """Sets up the "apollo" logger tree (apollo.main, apollo.scraping, etc.)
    with a console handler and, when the log directory is writable, a rotating
    + gzipping file handler too — so logs survive container restarts, are
    readable directly from the host at ./logs, and don't grow unbounded."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.setLogRecordFactory(_record_factory)

    root = logging.getLogger("apollo")
    root.setLevel(level)
    root.propagate = False
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s %(filename)s:%(lineno)d: %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = Path(settings.log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "apollo.log",
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
        )
        file_handler.setFormatter(fmt)
        # Rotated files land as apollo.log.1.gz, apollo.log.2.gz, ... instead
        # of the default uncompressed apollo.log.1, apollo.log.2, ...
        file_handler.rotator = _gzip_and_remove
        file_handler.namer = lambda name: f"{name}.gz"
        root.addHandler(file_handler)
    except OSError:
        root.warning("Could not open log directory %s — file logging disabled", log_dir)

    # Quiet down noisy third-party loggers so "apollo.*" signal isn't buried.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
