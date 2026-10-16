"""
navigation.py — everything related to moving the robot between named
locations (home, plate_pickup, meal serving slots, resident seats).

navigate_to() drives by running the route scripts (route_part1/2/3.py),
each of which covers one fixed leg of the room:

    route_part1.py : base    -> kitchen
    route_part2.py : kitchen -> table
    route_part3.py : table   -> base

Those scripts are legs, not destinations, but job_service.py asks for
destinations ("plate_pickup", "seat_1", "home_location"). routes.yml
bridges the two: it groups location_ids into zones and declares which
script drives which zone-to-zone segment. This module tracks the zone the
robot is currently in, works out the shortest sequence of segments to the
requested location's zone, and runs those scripts in order. That keeps
navigate_to(location_id, locations)'s signature -- and therefore every
call site in job_service.py -- exactly as it was under the old stub.

Consequences worth knowing:

- Locations in the same zone need no driving. The four meal slots all sit
  in the kitchen zone, so the per-meal navigate_to() calls inside a job
  are no-ops (logged as navigate_skipped), and only the plate_pickup ->
  seat and seat -> home moves actually drive.

- Chained jobs pass through base. The graph is a one-way loop
  (base -> kitchen -> table -> base), so a second job asking for
  plate_pickup while the robot is at the table runs route_part3.py then
  route_part1.py. The robot drives through base without stopping there;
  "skip going home" in the chaining logic means it doesn't idle at home,
  not that it can teleport across the room.

- Route scripts run as subprocesses, not imports, and via their own
  interpreter (config.ROUTE_PYTHON). They pull in robot_core, which lives
  in the older lerobot 0.4.1 fork that this app's environment can't import
  -- the same reason robot_connection.py doesn't handle the xlerobot kind.
  A subprocess is that "bridge process": one crashed route can't take the
  service down with it, and the two lerobot versions never share an
  interpreter. Route stdout is echoed live, prefixed with the script name.
  The process handling (live output, timeout, one-SIGINT stop, and the
  HARDWARE_SETTLE_SECONDS gap before any bus is reopened) lives in
  hw_process.py, shared with the policy rollouts that run between legs.

- A failed or timed-out route leaves the robot somewhere unknown. This
  module then refuses to plan anything further (position_known() goes
  False) rather than guessing and running a leg from the wrong place;
  run_service() sees that and shuts down. Re-home the robot and restart
  (or call set_current_zone() if you're driving this module yourself).
"""

import os
from collections import deque

import yaml

import config
import hw_process
from event_logger import log_event


# Parsed routes.yml, loaded once. Kept at module level rather than passed
# through navigate_to() so the (location_id, locations) signature that
# job_service.py calls stays unchanged.
_routes = None

# Zone the robot is believed to be in. None means "unknown" -- either
# routes.yml hasn't been loaded yet, or a route failed partway.
_current_zone = None


def load_locations() -> dict:
    """
    Reads locations.yml into a dict keyed by location_id -> coordinates.
    Called once at app startup and passed around, rather than re-reading
    the file on every navigate_to() call.
    """
    with open(config.LOCATIONS_FILE, "r") as f:
        data = yaml.safe_load(f)
    return {loc["location_id"]: loc["location_coordinates"] for loc in data["locations"]}


def load_routes() -> dict:
    """
    Reads routes.yml into the zone graph used to plan drives, and sets the
    robot's assumed starting zone.

    Called once at app startup so a bad routes.yml (unknown zone, missing
    script file, a location_id in two zones) fails immediately at launch
    instead of halfway through a job with a plate in the gripper.
    """
    global _routes, _current_zone

    with open(config.ROUTES_FILE, "r") as f:
        data = yaml.safe_load(f)

    zones = data.get("zones") or {}
    if not zones:
        raise ValueError(f"{config.ROUTES_FILE} defines no zones")

    # location_id -> zone, rejecting any location claimed by two zones:
    # that would make the robot's destination ambiguous
    location_zone = {}
    for zone_id, location_ids in zones.items():
        for location_id in (location_ids or []):
            if location_id in location_zone:
                raise ValueError(
                    f"location_id '{location_id}' is listed in both "
                    f"'{location_zone[location_id]}' and '{zone_id}' in {config.ROUTES_FILE}"
                )
            location_zone[location_id] = zone_id

    segments = {}  # (from_zone, to_zone) -> script filename
    edges = {}     # from_zone -> [to_zone, ...]
    for segment in (data.get("segments") or []):
        from_zone, to_zone = segment.get("from"), segment.get("to")
        script = segment.get("script")

        for label, zone_id in (("from", from_zone), ("to", to_zone)):
            if zone_id not in zones:
                raise ValueError(
                    f"segment {label}: '{zone_id}' in {config.ROUTES_FILE} "
                    f"is not a declared zone. Known zones: {sorted(zones)}"
                )
        if not script:
            raise ValueError(f"segment {from_zone} -> {to_zone} has no 'script' set")

        script_path = os.path.join(config.ROUTE_SCRIPTS_DIR, script)
        if not os.path.isfile(script_path):
            raise ValueError(
                f"route script '{script}' for segment {from_zone} -> {to_zone} "
                f"not found at {os.path.abspath(script_path)} -- check "
                f"config.ROUTE_SCRIPTS_DIR"
            )

        segments[(from_zone, to_zone)] = script
        edges.setdefault(from_zone, []).append(to_zone)

    if not segments:
        raise ValueError(f"{config.ROUTES_FILE} defines no segments")

    start_zone = data.get("start_zone")
    if start_zone not in zones:
        raise ValueError(
            f"start_zone '{start_zone}' in {config.ROUTES_FILE} is not a declared zone. "
            f"Known zones: {sorted(zones)}"
        )

    _routes = {
        "zones": zones,
        "location_zone": location_zone,
        "segments": segments,
        "edges": edges,
    }
    _current_zone = start_zone
    log_event("routes_loaded",
              zones=len(zones), segments=len(segments), start_zone=start_zone)
    return _routes


def current_zone():
    """The zone the robot is believed to be in, or None if unknown."""
    return _current_zone


def position_known() -> bool:
    """
    False once a route has failed partway, i.e. the robot is somewhere
    between two zones and no further route can be planned safely.
    run_service() checks this to decide whether to keep working.
    """
    return _current_zone is not None


def set_current_zone(zone_id: str) -> None:
    """
    Declares where the robot physically is -- used by main.py's
    --start-zone, and by hand after re-homing a robot whose route failed.
    """
    global _current_zone

    if _routes is not None and zone_id not in _routes["zones"]:
        raise ValueError(
            f"'{zone_id}' is not a declared zone. Known zones: {sorted(_routes['zones'])}"
        )
    _current_zone = zone_id
    log_event("position_set", zone=zone_id)


def _plan(from_zone: str, to_zone: str) -> list:
    """
    Shortest sequence of segments from one zone to another, as a list of
    (from_zone, to_zone) pairs. Breadth-first over routes.yml's segments,
    which are directed -- route_part1.py drives base -> kitchen and is
    never run backwards to get from the kitchen to base.
    """
    edges = _routes["edges"]

    previous = {from_zone: None}
    queue = deque([from_zone])
    while queue:
        zone = queue.popleft()
        if zone == to_zone:
            break
        for next_zone in edges.get(zone, []):
            if next_zone not in previous:
                previous[next_zone] = zone
                queue.append(next_zone)

    if to_zone not in previous:
        raise ValueError(
            f"no route from zone '{from_zone}' to zone '{to_zone}' -- "
            f"check the segments in {config.ROUTES_FILE}"
        )

    path = []
    zone = to_zone
    while previous[zone] is not None:
        path.append((previous[zone], zone))
        zone = previous[zone]
    path.reverse()
    return path


def _run_route_script(script: str, from_zone: str, to_zone: str) -> None:
    """
    Runs one route script to completion, echoing its output live.

    Raises RuntimeError on a non-zero exit or a timeout. Both mean the
    robot did not arrive, so the caller must treat its position as
    unknown -- an aborted route stops wherever it stopped.
    """
    script_path = os.path.join(config.ROUTE_SCRIPTS_DIR, script)
    command = [config.ROUTE_PYTHON, script_path]

    log_event("route_segment_start",
              from_zone=from_zone, to_zone=to_zone, script=script)
    print(f"[route] {from_zone} -> {to_zone} via {script}")

    result = hw_process.run(
        command,
        label=script,
        timeout_s=config.ROUTE_TIMEOUT_SECONDS,
        grace_s=config.ROUTE_SIGINT_GRACE_SECONDS,
        cwd=config.ROUTE_SCRIPTS_DIR,
        stdin=hw_process.INHERIT,  # unchanged: robot_core swaps stdin itself at connect()
        tail_lines=config.ROUTE_OUTPUT_TAIL_LINES,
    )

    if result.timed_out:
        raise RuntimeError(
            f"route script '{script}' ({from_zone} -> {to_zone}) did not finish within "
            f"{config.ROUTE_TIMEOUT_SECONDS}s and was stopped"
        )

    if result.returncode != 0:
        detail = " / ".join(result.tail) if result.tail else "no output"
        raise RuntimeError(
            f"route script '{script}' ({from_zone} -> {to_zone}) exited with code "
            f"{result.returncode}. Last output: {detail}"
        )

    log_event("route_segment_complete",
              from_zone=from_zone, to_zone=to_zone, script=script)


def navigate_to(location_id: str, locations: dict) -> None:
    """
    Moves the robot to the named location by running whichever route
    scripts lead from its current zone to that location's zone.

    Does nothing if the location is already in the current zone (e.g. the
    meal slots, all reachable from the one kitchen stop).

    Raises if the location is unknown, unreachable, the robot's position
    is unknown, or a route script fails -- job_service.py turns that into
    a failed job rather than serving a resident a plate the robot never
    actually collected.
    """
    global _current_zone

    log_event("navigate_to_called", location_id=location_id, current_zone=_current_zone)

    # --no-navigation: log the intent and stay put
    if not locations:
        log_event("null_locations", location_id=location_id)
        return

    coordinates = locations.get(location_id)
    if coordinates is None:
        raise ValueError(
            f"No coordinates found for location_id '{location_id}' — check locations.yml"
        )

    if _routes is None:
        raise RuntimeError(
            "routes.yml has not been loaded — call navigation.load_routes() at startup"
        )

    target_zone = _routes["location_zone"].get(location_id)
    if target_zone is None:
        raise ValueError(
            f"location_id '{location_id}' is not assigned to a zone in {config.ROUTES_FILE} — "
            f"add it to one of: {sorted(_routes['zones'])}"
        )

    if _current_zone is None:
        raise RuntimeError(
            "the robot's position is unknown (a route was aborted partway), so no route "
            "can be planned. Drive it back to a known zone and restart the app."
        )

    if target_zone == _current_zone:
        log_event("navigate_skipped",
                  location_id=location_id, zone=target_zone, reason="already_in_zone")
        return

    path = _plan(_current_zone, target_zone)

    log_event("navigate_start",
              location_id=location_id,
              from_zone=_current_zone,
              to_zone=target_zone,
              route="->".join([_current_zone] + [step_to for _, step_to in path]),
              coordinates=coordinates)

    for step_from, step_to in path:
        script = _routes["segments"][(step_from, step_to)]
        try:
            _run_route_script(script, step_from, step_to)
        except Exception:
            # the robot stopped mid-leg: it is no longer in step_from, and
            # it never reached step_to. Refuse to plan from a guess.
            _current_zone = None
            log_event("position_lost",
                      failed_segment=f"{step_from}->{step_to}", script=script)
            raise
        _current_zone = step_to

    log_event("navigate_complete", location_id=location_id, zone=_current_zone)
