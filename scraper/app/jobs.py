"""In-memory job tracking for POST /scrape's submit-and-poll model (see
main.py). A plain dict is enough here — this app runs as a single replica
(api.tf pins replicas=1, since Playwright scrapes aren't designed to run
concurrently across replicas anyway), so there's no case where a job created
on one process needs to be visible to another. A restart loses in-flight job
status same as it always would have lost an in-flight synchronous request —
no worse than before, just a different shape of "worse."
"""
import time
import uuid
from typing import Literal

JobStatus = Literal["queued", "running", "done", "error"]

_jobs: dict[str, dict] = {}

# Bounds memory rather than growing forever — evicts finished jobs first
# (oldest first) once there are more than this many tracked. A job that's
# still queued/running is never evicted out from under a caller still
# polling it.
_MAX_JOBS = 200


def create_job(url: str) -> str:
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {
        "job_id": job_id,
        "url": url,
        "status": "queued",
        "created_at": time.time(),
        "result": None,
        "error": None,
    }
    _evict_old_jobs()
    return job_id


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def set_running(job_id: str) -> None:
    _jobs[job_id]["status"] = "running"


def set_done(job_id: str, result: dict) -> None:
    _jobs[job_id]["status"] = "done"
    _jobs[job_id]["result"] = result


def set_error(job_id: str, status_code: int, detail: str) -> None:
    _jobs[job_id]["status"] = "error"
    _jobs[job_id]["error"] = {"status_code": status_code, "detail": detail}


def _evict_old_jobs() -> None:
    if len(_jobs) <= _MAX_JOBS:
        return
    finished = sorted(
        (j for j in _jobs.values() if j["status"] in ("done", "error")),
        key=lambda j: j["created_at"],
    )
    for job in finished[: len(_jobs) - _MAX_JOBS]:
        _jobs.pop(job["job_id"], None)
