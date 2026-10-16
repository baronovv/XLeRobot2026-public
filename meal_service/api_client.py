"""
api_client.py — all communication with the cloud admin panel API.

Kept separate from main.py so the HTTP/API details (headers, endpoints,
response shape) are in one place, isolated from the job-execution logic.
"""

import requests

import config
from event_logger import log_event


def api_headers() -> dict:
    return {"Authorization": f"Bearer {config.API_KEY}"}


def get_pending_job() -> dict | None:
    """
    Polls the admin panel for the oldest pending job.

    Two confirmed response shapes:
    - No job pending: {"job": null}
    - Job found: the job object directly, e.g.
      {"job_id": 5, "seat_id": "seat_3", "meals": [...]}
      (not wrapped in a "job" key — confirmed against a real response)

    Returns the job dict, or None if no job is pending.

    Raises on any transport error, non-2xx status, or unparseable body.
    An empty body is treated as an error rather than "no job": silently
    reading it as an empty queue would idle the robot through a real
    backlog. Callers are expected to retry -- see job_service.
    """
    resp = requests.get(
        f"{config.API_BASE_URL}/api/public/robot/jobs/pending",
        headers=api_headers(),
        timeout=config.API_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()

    if not resp.text.strip():
        raise ValueError("empty response body from /jobs/pending (expected JSON)")

    data = resp.json()

    # the "no job pending" case comes back wrapped: {"job": null}
    if isinstance(data, dict) and "job" in data and data["job"] is None:
        return None

    return data if data else None


def set_job_status(job_id: str, status: str) -> None:
    """PATCHes job status on the admin panel."""
    resp = requests.patch(
        f"{config.API_BASE_URL}/api/public/robot/jobs/{job_id}",
        headers=api_headers(),
        json={"status": status},
        timeout=config.API_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    log_event("job_status_updated", job_id=job_id, status=status)
