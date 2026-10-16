"""
test_script.py — run ONE policy exactly as the service would: same command,
same ports/cameras, same checks. No admin panel, no driving.

Use it with the robot parked at a stop to check a policy before a full run:

    python test_script.py dessert_banana --dry-run     # only print the command
    python test_script.py dessert_banana               # run it on the arm
    python test_script.py plate_serve_left --port left=/dev/ttyACM1 --cam head=/dev/video8
"""

import argparse

import policies as policy_runner
from event_logger import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("policy_id", help="a policy_id from policies.yml")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the lerobot-rollout command, don't run it")
    policy_runner.add_hardware_args(parser)
    args = parser.parse_args()

    setup_logging()
    policies = policy_runner.load_policies()
    policy_runner.load_rollout_config(
        port_overrides=policy_runner.parse_assignments(args.port, "--port"),
        cam_overrides=policy_runner.parse_assignments(args.cam, "--cam"),
    )
    policy_runner.set_dry_run(args.dry_run, pause_seconds=0)
    policy_runner.validate_setup(policies, strict=not args.dry_run, only=[args.policy_id])

    ran = policy_runner.execute_policy(args.policy_id, policies)
    print(f"[test] {args.policy_id}: {'done' if ran else 'skipped (no policy_path)'}")


if __name__ == "__main__":
    main()
