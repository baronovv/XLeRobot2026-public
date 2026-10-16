# config.py
# Central config — nothing hardcoded elsewhere in the app.

API_BASE_URL = "https://care-tray-admin.lovable.app"  # cloud admin panel API
import os
API_KEY = os.environ.get("ROBOT_API_KEY", "")  # export ROBOT_API_KEY=... before running

POLL_INTERVAL_SECONDS = 60  # "requests every 1 minute" per spec
NO_JOB_TIMEOUT_SECONDS = 120  # exit the app after this long with no pending jobs found

# Status sent when a job aborts mid-execution. Confirm the admin panel
# actually accepts this value -- if it rejects it, the job stays "pending"
# and gets blocked by run_service() instead of retried forever.
FAILED_STATUS = "failed"

API_TIMEOUT_SECONDS = 10  # per-request timeout; without this a hung TCP
                          # connection blocks the poll loop indefinitely
MAX_CONSECUTIVE_POLL_FAILURES = 5  # give up and exit after this many
                                   # failed polls in a row

POLICIES_FILE = "policies.yml"
LOCATIONS_FILE = "locations.yml"
ROBOT_FILE = "robot.yml"
ROUTES_FILE = "routes.yml"  # zone graph mapping locations -> route scripts
ROLLOUT_FILE = "rollout.yml"  # arm ports / cameras / fps for lerobot-rollout

# --- Route scripts (route_part1/2/3.py) ------------------------------------
# Directory holding route_part*.py and the robot_core.py they import. Set an
# absolute path if they live outside this app's directory.
ROUTE_SCRIPTS_DIR = "/home/jetson8/robotmovement"

# Interpreter used to run them. The route scripts import robot_core, which
# needs the older lerobot 0.4.1 fork -- a different environment from the one
# this app runs under -- so this is deliberately NOT sys.executable. Point it
# at that env's python, e.g.
# "/home/jetson8/miniconda3/envs/lerobot/bin/python".
ROUTE_PYTHON = "/home/jetson8/miniconda3/envs/lerobot/bin/python"

# Longest a single leg may take before it's assumed stuck and stopped. Size
# this above the slowest real leg -- a route interrupted here leaves the robot
# in an unknown position and shuts the service down.
ROUTE_TIMEOUT_SECONDS = 180
ROUTE_SIGINT_GRACE_SECONDS = 10  # time a route gets to stop its wheels after SIGINT;
                                 # SIGKILL mid-transaction corrupts bus state
ROUTE_OUTPUT_TAIL_LINES = 15    # lines of route output quoted in a failure message

# --- Hardware handoffs ------------------------------------------------------
# Minimum gap between one hardware process (route script or policy rollout)
# releasing the motor buses/cameras and the next one opening them. Zero-gap
# reopens of the same Feetech bus hang. Applies route->route, route->policy,
# policy->route and policy->policy, so it is also the robot's pause between
# arriving at a stop and the arm starting.
HARDWARE_SETTLE_SECONDS = 1.5

# --- Policy execution (lerobot-rollout, see policies.py / rollout.yml) --------
DEFAULT_EXECUTION_SECONDS = 60     # policy run time when policies.yml doesn't set
                                   # execution_seconds (= lerobot's default episode)
POLICY_TIMEOUT_MARGIN_SECONDS = 180  # allowed on top of execution_seconds for model
                                     # load, camera warmup, video encoding and the
                                     # return-to-rest before the rollout is stopped
POLICY_SIGINT_GRACE_SECONDS = 60   # time a stopped rollout gets to save, return the
                                   # arm to rest and disconnect before SIGKILL
POLICY_OUTPUT_TAIL_LINES = 15      # lines of rollout output quoted in a failure message
POLICY_DRY_RUN_SECONDS = 5         # length of each simulated stop under --policy-dry-run

LOG_DIR = "logs"  # each run creates its own timestamped file inside this directory
