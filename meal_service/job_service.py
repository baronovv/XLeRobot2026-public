"""
job_service.py — the meal service's core logic: executing one Serving
Job end to end, and the poll/chain loop that decides when to run one.

Pulled out of main.py so main.py stays a thin orchestrator (setup +
one call into run_service()), and this file owns the actual behavior
described in slide 4 of the spec:

  loop forever:
    poll for pending jobs (every POLL_INTERVAL_SECONDS)
    if no job found -> loop again
    if job found:
        send job_status = in_progress
        if a meal_type has no trained policy -> job failed, robot doesn't move
        navigate to plate_pickup location                 (place B, kitchen)
        execute plate_pickup policy (skipped while it has no policy_path)
        for each meal in meals:
            navigate to meal.serving_slot                 (same stop)
            execute policy for meal.meal_type
        navigate to seat_id location                      (place C, table)
        execute each meal's serve_policy (once per distinct serve_policy)
        send job_status = done
        if more jobs pending -> start next job immediately (skip going home)
        else -> navigate to home_location, end this execution cycle

Every policy is one lerobot-rollout run (policies.py) that blocks until the
arm is back at rest and its port is released, so the robot stays parked at
each stop for the whole policy -- policies run one at a time, never while
driving.

QR-code meal matching is explicitly out of scope for this version.

If any step of a job fails (navigation or policy execution -- e.g. a
hardware fault like the Feetech overload error seen during testing),
the whole job is aborted and marked "failed" rather than continuing on
to later steps: a partially-completed job (e.g. a policy failed
mid-grip) shouldn't proceed to serving a resident. The failure is
logged and run_service()'s poll loop continues to the next job rather
than crashing the app. If you'd rather have finer-grained recovery
(e.g. skip just the failed meal and still serve the rest), that's a
deliberate product decision to revisit, not a default to assume here.

Nothing in this file knows how the robot gets anywhere -- it names
destinations and navigation.py decides which route scripts to run to
reach them, which is why the flow above didn't change when navigation
went from a stub to real driving. Two things follow from navigation
being real, and both live here:

  - navigate_to() drives hardware now, so the return-home call at the
    end of the loop is wrapped: a failure there is a logged event, not
    a crashed service.
  - a route that aborts partway leaves the robot in an unknown place,
    and navigation refuses to plan from a guess. The loop checks
    position_known() and stops cleanly rather than grinding the whole
    pending queue into failed jobs.
"""

import time

import config
from event_logger import log_event
from navigation import navigate_to, position_known, current_zone
from policies import execute_policy, policy_configured, serve_policy_for
from api_client import get_pending_job, set_job_status


# Returned by _next_actionable_job() when the poll itself failed. This is
# deliberately NOT None: "the queue is empty" and "I couldn't find out"
# demand different handling -- the first means go home and start the
# no-job timeout, the second means retry and touch nothing.
_POLL_FAILED = object()


def _safe_set_status(job_id, status: str) -> bool:
    """
    PATCHes job status, swallowing (and logging) any transport or API
    error. Returns True only if the panel accepted the update.

    The caller uses the return value to decide whether the job reached a
    terminal state. A job whose terminal status was rejected stays
    "pending" on the panel and would be handed straight back on the next
    poll -- see _next_actionable_job().
    """
    try:
        set_job_status(job_id, status)
        return True
    except Exception as e:
        log_event("job_status_update_failed", job_id=job_id, status=status, error=str(e))
        print(f"[job] could not set job {job_id} status to '{status}': {e}")
        return False


def _next_actionable_job(attempted: set):
    """
    Polls for the next pending job, filtering out any job_id this
    process has already attempted. Returns _POLL_FAILED if the request
    itself failed, so the caller can distinguish that from an empty
    queue.

    job_ids are unique per job panel-side, so seeing one twice can only
    mean the job never left "pending" -- either its terminal PATCH was
    rejected, or the panel accepted it but didn't actually change the
    status. Both cases are indistinguishable from here, and both are
    fatal without this guard: the chain loop re-fetches the same job,
    re-runs it, and repeats with no sleep anywhere in the loop.

    Treating a repeat as "no job available" drops the caller back into
    its normal poll interval and no-job timeout, so a stuck job costs
    one request per POLL_INTERVAL_SECONDS instead of thousands per
    second, and shows up in the log as job_stuck_pending.
    """
    try:
        job = get_pending_job()
    except Exception as e:
        log_event("poll_failed", error=str(e))
        print(f"[poll] could not reach the admin panel: {e}")
        return _POLL_FAILED

    if job is None:
        return None

    if job.get("job_id") in attempted:
        log_event("job_stuck_pending", job_id=job.get("job_id"))
        return None

    return job


def execute_job(job: dict, policies: dict, locations: dict) -> bool:
    """
    Runs one Serving Job end to end, per slide 4's flow.

    Expected job shape:
    {
        "job_id": "...",
        "seat_id": "seat_1",
        "meals": [
            {"meal_name": "...", "meal_type": "soup", "serving_slot": "serving_soup"},
            ...
        ]
    }

    Each meal_type is a policy_id in policies.yml (one policy folder per
    product); that entry's serve_policy is what runs at the seat.

    If any step raises, the job is marked "failed" and execution stops
    -- it does not propagate the exception to the caller, so
    run_service()'s poll loop can continue to the next job.
    """
    job_id = job["job_id"]
    log_event("job_started", job_id=job_id)

    if not _safe_set_status(job_id, "in_progress"):
        # couldn't even claim the job -- don't start moving hardware for
        # a job the panel doesn't think is in progress
        log_event("job_abandoned_no_claim", job_id=job_id)
        return False

    # A product without a trained policy can't be picked up, so refuse the
    # job before driving anywhere rather than serving an empty tray.
    # (Skipped under --no-policies, where policies is None.)
    if policies:
        untrained = [meal.get("meal_type") for meal in job.get("meals", [])
                     if not policy_configured(meal.get("meal_type"), policies)]
        if untrained:
            log_event("job_rejected_no_policy", job_id=job_id, meal_types=untrained)
            print(f"[job] job {job_id}: no policy_path in policies.yml for {untrained} "
                  f"-- marking failed without moving")
            return _safe_set_status(job_id, config.FAILED_STATUS)

    try:
        # place B: navigate to plate pickup, execute the plate_pickup policy
        navigate_to("plate_pickup", locations)
        execute_policy("plate_pickup", policies)

        # for each meal on the job, navigate to its serving slot (same stop)
        # and run the policy matching its meal_type; remember which policy
        # serves it at the seat
        serve_policies = []
        for meal in job["meals"]:
            navigate_to(meal["serving_slot"], locations)
            execute_policy(meal["meal_type"], policies)
            serve_id = serve_policy_for(meal["meal_type"], policies)
            if serve_id not in serve_policies:
                serve_policies.append(serve_id)

        # place C: navigate to the resident's seat, serve with the arm(s)
        # the meals were picked with
        navigate_to(job["seat_id"], locations)
        for serve_id in serve_policies:
            execute_policy(serve_id, policies)

    except Exception as e:
        log_event("job_failed", job_id=job_id, error=str(e))
        print(f"[job] job {job_id} failed: {e}")
        return _safe_set_status(job_id, config.FAILED_STATUS)

    if not _safe_set_status(job_id, "done"):
        return False
    log_event("job_finished", job_id=job_id)
    return True


def run_service(policies: dict, locations: dict) -> None:
    """
    The main poll/execute/chain loop. Runs until either:
    - the app is killed externally, or
    - no pending job has been found for NO_JOB_TIMEOUT_SECONDS, in which
      case the app logs this and exits cleanly.

    Behavior:
    - polls for a pending job every POLL_INTERVAL_SECONDS
    - once a job is found, executes it, then immediately checks for
      another pending job before going home (the "More jobs?" branch)
    - only navigates home once the queue is empty
    - tracks time since a job was last seen; if that exceeds
      NO_JOB_TIMEOUT_SECONDS, exits instead of polling forever
    - a failed job (see execute_job) does not stop the loop -- it
      moves on to the next pending job (or back to polling) the same
      as a successfully completed one
    """
    last_job_seen_at = time.monotonic()
    attempted = set()  # every job_id this process has already run
    poll_failures = 0  # consecutive failed polls

    while True:
        # A route aborted partway leaves the robot between zones, so
        # navigation can no longer plan a drive (see navigation.py). Every
        # further job would fail at its first move, so stop cleanly here
        # instead of marking the whole queue failed one job at a time.
        if locations and not position_known():
            log_event("position_unknown_exit", last_known_zone=current_zone())
            print("[service] robot position unknown after a failed route — stopping. "
                  "Drive it back to a known zone and restart.")
            return

        job = _next_actionable_job(attempted)

        if job is _POLL_FAILED:
            poll_failures += 1
            if poll_failures >= config.MAX_CONSECUTIVE_POLL_FAILURES:
                log_event("poll_failures_exit", consecutive_failures=poll_failures)
                return

            # back off exponentially, capped at the normal poll interval
            backoff = min(config.POLL_INTERVAL_SECONDS, 2 ** poll_failures)
            log_event("poll_retry_scheduled",
                      consecutive_failures=poll_failures,
                      retry_in_seconds=round(backoff, 1))
            time.sleep(backoff)

            # an outage is not evidence the queue is empty, so don't let
            # time spent unable to reach the panel count toward the
            # no-job timeout
            last_job_seen_at += backoff
            continue

        poll_failures = 0

        if job is None:
            elapsed = time.monotonic() - last_job_seen_at
            if elapsed >= config.NO_JOB_TIMEOUT_SECONDS:
                log_event("no_jobs_timeout_exit", elapsed_seconds=round(elapsed))
                return  # exits run_service -> main.py has nothing left to do -> app exits

            # no job found yet, but still within the timeout window — wait and poll again
            log_event("no_job_found", elapsed_since_last_job_seconds=round(elapsed))
            time.sleep(config.POLL_INTERVAL_SECONDS)
            continue

        # job found — reset the timeout clock
        last_job_seen_at = time.monotonic()

        # execute it, then chain straight into the next pending job if one
        # exists, per the "More jobs?" branch in slide 4
        while job is not None and job is not _POLL_FAILED:
            # record before executing: if this job crashes the process or
            # never clears, we must not pick it up again on the next poll
            attempted.add(job.get("job_id"))
            execute_job(job, policies, locations)

            # a job that lost the robot's position ends the chain here:
            # neither the next job nor the drive home can be planned, so
            # don't mark another job failed on the way out
            if locations and not position_known():
                break

            job = _next_actionable_job(attempted)
            if job is not None and job is not _POLL_FAILED:
                last_job_seen_at = time.monotonic()

        if locations and not position_known():
            continue  # the check at the top of the loop logs this and exits

        if job is _POLL_FAILED:
            # the queue is not confirmed empty -- don't drive home on a
            # guess; go back to the outer loop and retry the poll
            log_event("chain_ended_poll_failed")
            continue

        # no more jobs left — return home before resuming the poll loop.
        # Guarded because this call now drives real hardware: an unhandled
        # route failure here would escape run_service() and crash the app,
        # where the same failure inside a job is only a failed job.
        try:
            navigate_to("home_location", locations)
            log_event("queue_empty_returned_home")
        except Exception as e:
            log_event("return_home_failed", error=str(e))
            print(f"[job] could not return home: {e}")
