"""
main.py — Meal Service Jetson app, entry point only.

No logic lives here. This file just:
    1. sets up logging
    2. loads policies.yml + rollout.yml, locations.yml and routes.yml, and
       checks them, so a bad path/port fails at launch instead of after the
       robot has driven to a stop
    3. hands off to job_service.run_service(), which owns the actual
       poll/execute/chain behavior described in slide 4 of the spec

See job_service.py for the real logic, and navigation.py / policies.py /
api_client.py / event_logger.py for the modules it depends on.

Examples:
    python main.py
    python main.py --port right=/dev/ttyACM0 --cam head=/dev/video8
    python main.py --policy-dry-run          # drive + stop at each place, arms idle
    python main.py --no-policies --no-navigation
"""

import argparse

import navigation
import policies as policy_runner
from event_logger import setup_logging, log_event
from navigation import load_locations, load_routes
from job_service import run_service


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-navigation", action="store_true")
    parser.add_argument("--no-policies", action="store_true")
    parser.add_argument(
        "--policy-dry-run", action="store_true",
        help="print each lerobot-rollout command and pause instead of running "
             "it -- the robot still stops at each place, the arms don't move",
    )
    parser.add_argument(
        "--start-zone",
        help="zone the robot is physically in right now (default: routes.yml's "
             "start_zone). Getting this wrong means the first route drives from "
             "the wrong place.",
    )
    policy_runner.add_hardware_args(parser)  # --port ARM=DEV, --cam CAMERA=DEV
    args = parser.parse_args()

    setup_logging()

    policies = None
    if not args.no_policies:
        policies = policy_runner.load_policies()
        policy_runner.load_rollout_config(
            port_overrides=policy_runner.parse_assignments(args.port, "--port"),
            cam_overrides=policy_runner.parse_assignments(args.cam, "--cam"),
        )
        policy_runner.set_dry_run(args.policy_dry_run)
        policy_runner.validate_setup(policies, strict=not args.policy_dry_run)

    locations = None if args.no_navigation else load_locations()

    # routes.yml is loaded (and validated) up front so a bad zone/segment or a
    # missing route script fails at launch, not mid-job
    if not args.no_navigation:
        load_routes()
        if args.start_zone:
            navigation.set_current_zone(args.start_zone)

    log_event("app_started", start_zone=navigation.current_zone(),
              policies="off" if args.no_policies else ("dry_run" if args.policy_dry_run else "on"))

    try:
        run_service(policies, locations)
    except KeyboardInterrupt:
        log_event("app_stopped_by_operator")
        print("\n[app] stopped by operator")

if __name__ == "__main__":
    main()
