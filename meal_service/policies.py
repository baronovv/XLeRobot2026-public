"""
policies.py — runs a trained policy on one arm by launching `lerobot-rollout`
as a subprocess, one policy at a time. The robot is stopped for the whole run.

Why a subprocess instead of the old in-process inference:
  - it is the exact command each policy was validated with by hand, so a
    policy that works from the terminal works here
  - the rollout opens its arm's port and cameras and closes them on exit, so
    nothing holds /dev/ttyACM* when the next route script needs the bus (the
    old cached connection in robot_connection.py did)
  - camera names, fps and pre/post-processing come from lerobot's own code
  - a crashing policy can't take the service down

Where things are configured:
  policies.yml  per policy: arm, policy_path, task_instruction,
                execution_seconds, and for products the serve_policy to run
                at the table. policy_id of a product == the admin panel's
                meal_type, so each product keeps its own policy folder.
  rollout.yml   per arm: port, robot.id, which physical camera feeds each
                camera name the policy was trained with (top/wrist);
                physical camera -> device; fps; strategy.
Ports and camera devices can be overridden at launch (--port / --cam) when
/dev/ttyACM* or /dev/video* get renumbered.

What one run looks like, for an arm=right policy (compare with the manual
command -- the differences are deliberate):
  lerobot-rollout --strategy.type=episodic --robot.type=so101_follower
    --robot.port=<right port> --robot.id=<right id>
    --robot.cameras="{ top: {...}, wrist: {...} }" --display_data=false
    --dataset.repo_id=<user>/rollout_<policy_id>
    --dataset.root=<dataset_root_dir>/<policy_id>_<timestamp>   (new dir every run:
                    lerobot refuses to create a dataset in an existing folder)
    --dataset.single_task="<task>" --dataset.num_episodes=1  (one run per stop)
    --dataset.episode_time_s=<execution_seconds> --dataset.push_to_hub=false
    --policy.path=<policy_path> --dataset.fps=<fps>
    --fps=<fps>     (the control loop runs at --fps, default 30, NOT --dataset.fps)

Each command is printed as a copy-pasteable shell line before it runs, and
its full output is saved to logs/rollout_<policy_id>_<time>.log.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

import config
import hw_process
from event_logger import log_event


# rollout.yml after CLI overrides, set by load_rollout_config() at startup.
# Module-level (like navigation's routes) so execute_policy(policy_id,
# policies) keeps the signature job_service.py calls.
_rollout_cfg = None

_dry_run = False
_dry_run_pause = None

# lerobot stores a robot's calibration under calibration/robots/<Robot.name>/
_CALIBRATION_DIR_NAMES = {"so101_follower": "so_follower", "so100_follower": "so_follower"}

_CALIBRATION_PROMPT = "Press ENTER to use provided calibration file"
_CAMERA_MISMATCH = "Visual feature mismatch"


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load_policies() -> dict:
    """
    Reads policies.yml into a dict keyed by policy_id. Called once at
    startup and passed around.
    """
    with open(config.POLICIES_FILE, "r") as f:
        data = yaml.safe_load(f) or {}

    policies = {}
    for p in data.get("policies") or []:
        policy_id = p.get("policy_id")
        if not policy_id:
            raise ValueError(f"{config.POLICIES_FILE}: an entry has no policy_id")
        if policy_id in policies:
            raise ValueError(f"{config.POLICIES_FILE}: policy_id '{policy_id}' is listed twice")

        path = p.get("policy_path")
        policies[policy_id] = {
            "policy_path": os.path.expanduser(str(path)) if path else None,
            "arm": p.get("arm"),
            "task_instruction": p.get("task_instruction"),
            "execution_seconds": p.get("execution_seconds") or config.DEFAULT_EXECUTION_SECONDS,
            "serve_policy": p.get("serve_policy"),
            "extra_args": [str(a) for a in (p.get("extra_args") or [])],
        }
    return policies


def parse_assignments(values, flag: str) -> dict:
    """['right=/dev/ttyACM0', ...] -> {'right': '/dev/ttyACM0', ...}"""
    result = {}
    for value in values or []:
        name, sep, device = value.partition("=")
        if not sep or not name or not device:
            raise ValueError(f"{flag} expects NAME=DEVICE, got '{value}'")
        result[name.strip()] = device.strip()
    return result


def add_hardware_args(parser) -> None:
    """--port / --cam launch overrides, shared by main.py and test_script.py."""
    parser.add_argument(
        "--port", action="append", metavar="ARM=DEVICE",
        help="override an arm's serial port from rollout.yml, e.g. "
             "--port right=/dev/ttyACM0 (repeatable)",
    )
    parser.add_argument(
        "--cam", action="append", metavar="CAMERA=DEVICE",
        help="override a camera device from rollout.yml, e.g. "
             "--cam head=/dev/video8 (repeatable)",
    )


def load_rollout_config(port_overrides: dict = None, cam_overrides: dict = None) -> dict:
    """
    Reads rollout.yml, applies --port / --cam overrides, checks its
    structure, and stores it for execute_policy(). Called once at startup.
    """
    global _rollout_cfg

    with open(config.ROLLOUT_FILE, "r") as f:
        data = yaml.safe_load(f) or {}

    cameras = dict(data.get("cameras") or {})
    arms = {name: dict(arm or {}) for name, arm in (data.get("arms") or {}).items()}

    for arm_name, port in (port_overrides or {}).items():
        if arm_name not in arms:
            raise ValueError(f"--port {arm_name}=...: no arm '{arm_name}' in "
                             f"{config.ROLLOUT_FILE} (have: {sorted(arms)})")
        arms[arm_name]["port"] = port

    for cam_name, device in (cam_overrides or {}).items():
        if cam_name not in cameras:
            raise ValueError(f"--cam {cam_name}=...: no camera '{cam_name}' in "
                             f"{config.ROLLOUT_FILE} (have: {sorted(cameras)})")
        if isinstance(cameras[cam_name], dict):
            cameras[cam_name] = {**cameras[cam_name], "path": device}
        else:
            cameras[cam_name] = device

    for arm_name, arm in arms.items():
        for key in ("port", "id", "cameras"):
            if not arm.get(key):
                raise ValueError(f"{config.ROLLOUT_FILE}: arm '{arm_name}' has no '{key}'")
        for policy_cam, physical in arm["cameras"].items():
            if physical not in cameras:
                raise ValueError(
                    f"{config.ROLLOUT_FILE}: arm '{arm_name}' maps camera '{policy_cam}' to "
                    f"'{physical}', which is not listed under cameras: {sorted(cameras)}"
                )

    strategy = data.get("strategy", "episodic")
    if strategy not in ("episodic", "base"):
        raise ValueError(f"{config.ROLLOUT_FILE}: strategy must be 'episodic' or 'base', got '{strategy}'")

    _rollout_cfg = {
        "fps": int(data.get("fps", 15)),
        "camera_width": int(data.get("camera_width", 640)),
        "camera_height": int(data.get("camera_height", 480)),
        "cameras": cameras,
        "arms": arms,
        "robot_type": data.get("robot_type", "so101_follower"),
        "strategy": strategy,
        "dataset_user": data.get("dataset_user", "ktotomama"),
        "dataset_root_dir": os.path.expanduser(str(data.get("dataset_root_dir") or "~/lerobot_eval")),
        "display_data": bool(data.get("display_data", False)),
        "auto_confirm_calibration": bool(data.get("auto_confirm_calibration", False)),
        "rollout_bin": data.get("rollout_bin"),
        "extra_args": [str(a) for a in (data.get("extra_args") or [])],
    }
    log_event("rollout_config_loaded",
              fps=_rollout_cfg["fps"], strategy=strategy,
              ports={name: arm["port"] for name, arm in arms.items()},
              cameras={name: _camera_device(cam) for name, cam in cameras.items()})
    return _rollout_cfg


def set_dry_run(enabled: bool, pause_seconds: float = None) -> None:
    """Dry run: print each command and pause instead of running it."""
    global _dry_run, _dry_run_pause
    _dry_run = enabled
    _dry_run_pause = config.POLICY_DRY_RUN_SECONDS if pause_seconds is None else pause_seconds


# --------------------------------------------------------------------------
# queries used by job_service.py
# --------------------------------------------------------------------------

def policy_configured(policy_id: str, policies: dict) -> bool:
    """True if policy_id is in policies.yml with a policy_path set."""
    entry = (policies or {}).get(policy_id)
    return bool(entry and entry["policy_path"])


def serve_policy_for(meal_type: str, policies: dict) -> str:
    """Policy to run at the table for this product (its serve_policy,
    else the legacy 'plate_serve')."""
    entry = (policies or {}).get(meal_type) or {}
    return entry.get("serve_policy") or "plate_serve"


# --------------------------------------------------------------------------
# startup validation
# --------------------------------------------------------------------------

def _require_cfg() -> dict:
    if _rollout_cfg is None:
        raise RuntimeError("rollout.yml has not been loaded -- call "
                           "policies.load_rollout_config() at startup")
    return _rollout_cfg


def _rollout_bin():
    """lerobot-rollout from rollout.yml (pinned to the lerobot060 env, like
    config.ROUTE_PYTHON pins the lerobot env for the route scripts), else
    next to this app's python, else PATH."""
    configured = _require_cfg()["rollout_bin"]
    if configured:
        return os.path.expanduser(str(configured))
    sibling = os.path.join(os.path.dirname(sys.executable), "lerobot-rollout")
    if os.access(sibling, os.X_OK):
        return sibling
    return shutil.which("lerobot-rollout")


def _lerobot_version(rollout_bin: str):
    """(version, python) of the env rollout_bin belongs to, read with that
    env's own python -- the same interpreter the rollout will run on.
    version is None if it can't be read."""
    python = os.path.join(os.path.dirname(rollout_bin), "python")
    if not os.access(python, os.X_OK):
        return None, python
    try:
        out = subprocess.run(
            [python, "-c", "from importlib.metadata import version; print(version('lerobot'))"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, python
    version = out.stdout.strip()
    return (version or None), python


def _version_tuple(version: str):
    parts = []
    for piece in version.split(".")[:2]:
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _calibration_file(robot_type: str, robot_id: str):
    """Where lerobot looks for <robot_id>.json, or None if unknown type."""
    dir_name = _CALIBRATION_DIR_NAMES.get(robot_type)
    if dir_name is None:
        return None
    root = os.environ.get("HF_LEROBOT_CALIBRATION")
    if not root:
        home = os.environ.get("HF_LEROBOT_HOME")
        if not home:
            hf_home = os.environ.get("HF_HOME") or os.path.join(
                os.environ.get("XDG_CACHE_HOME", "~/.cache"), "huggingface")
            home = os.path.join(hf_home, "lerobot")
        root = os.path.join(home, "calibration")
    return Path(os.path.expanduser(root)) / "robots" / dir_name / f"{robot_id}.json"


def _camera_device(camera):
    return camera.get("path") if isinstance(camera, dict) else camera


def _is_index(device) -> bool:
    return isinstance(device, int) or (isinstance(device, str) and device.isdigit())


def validate_setup(policies: dict, strict: bool = True, only=None) -> None:
    """
    Checks at launch everything that would otherwise only fail after the
    robot has already driven to a stop: checkpoint folders, arm names,
    serve_policy references, and -- for the arms actually used -- that the
    ports, camera devices and calibration files exist.

    strict=False (dry runs) reports hardware problems as warnings.
    only: restrict the checks to these policy_ids.
    """
    cfg = _require_cfg()
    errors, hardware = [], []

    rollout_bin = _rollout_bin()
    if not rollout_bin or not os.access(rollout_bin, os.X_OK):
        hardware.append(f"lerobot-rollout not found ({rollout_bin or 'not next to this python, not on PATH'}) "
                        f"-- set rollout_bin in {config.ROLLOUT_FILE} to the lerobot060 env's "
                        f".../envs/lerobot060/bin/lerobot-rollout")
    else:
        version, python = _lerobot_version(rollout_bin)
        log_event("rollout_binary", path=rollout_bin, python=python, lerobot=version)
        print(f"[policy] using {rollout_bin} (lerobot {version or '?'})")
        if version is None:
            hardware.append(f"can't read the lerobot version with {python} -- is {rollout_bin} "
                            f"really from the lerobot060 env?")
        elif _version_tuple(version) < (0, 6):
            hardware.append(f"{rollout_bin} is lerobot {version}; the rollout flags used here need "
                            f"lerobot 0.6 (the lerobot060 env)")

    selected = {pid: e for pid, e in policies.items() if only is None or pid in only}
    for pid in (only or []):
        if pid not in policies:
            errors.append(f"'{pid}' is not a policy_id in {config.POLICIES_FILE}")

    used_arms = set()
    for pid, entry in selected.items():
        serve = entry["serve_policy"]
        if serve and serve not in policies:
            errors.append(f"'{pid}': serve_policy '{serve}' is not a policy_id in {config.POLICIES_FILE}")

        if not entry["policy_path"]:
            continue  # not trained yet: skipped / job rejected at runtime

        if entry["arm"] not in cfg["arms"]:
            errors.append(f"'{pid}': arm '{entry['arm']}' is not an arm in {config.ROLLOUT_FILE} "
                          f"({sorted(cfg['arms'])})")
        else:
            used_arms.add(entry["arm"])

        if not os.path.isfile(os.path.join(entry["policy_path"], "config.json")):
            errors.append(f"'{pid}': no config.json in {entry['policy_path']} -- policy_path must be "
                          f"the .../checkpoints/<step>/pretrained_model folder")

        if not entry["task_instruction"]:
            errors.append(f"'{pid}': task_instruction is empty")

        try:
            ok = float(entry["execution_seconds"]) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            errors.append(f"'{pid}': execution_seconds must be a positive number")

    for arm_name in sorted(used_arms):
        arm = cfg["arms"][arm_name]
        if not os.path.exists(arm["port"]):
            hardware.append(f"arm '{arm_name}': port {arm['port']} does not exist "
                            f"(ls -l /dev/serial/by-path/ /dev/ttyACM*)")
        calib = _calibration_file(cfg["robot_type"], arm["id"])
        if calib is not None and not calib.is_file():
            hardware.append(f"arm '{arm_name}': no calibration file {calib} for robot.id "
                            f"'{arm['id']}' -- wrong id in {config.ROLLOUT_FILE}? (lerobot-rollout "
                            f"would stop and ask to calibrate)")
        for policy_cam, physical in arm["cameras"].items():
            device = _camera_device(cfg["cameras"][physical])
            if not _is_index(device) and not os.path.exists(str(device)):
                hardware.append(f"arm '{arm_name}': camera '{policy_cam}' -> {physical} = {device} "
                                f"does not exist (ls -l /dev/v4l/by-id/)")

    if strict:
        errors.extend(hardware)
    else:
        for problem in hardware:
            print(f"[policy] WARNING: {problem}")
            log_event("policy_setup_warning", problem=problem)

    if errors:
        raise ValueError("policy setup problems:\n  - " + "\n  - ".join(errors))

    log_event("policy_setup_ok",
              configured=sorted(pid for pid, e in selected.items() if e["policy_path"]),
              arms=sorted(used_arms))


# --------------------------------------------------------------------------
# command
# --------------------------------------------------------------------------

def _yaml_scalar(value) -> str:
    """Value for the --robot.cameras mapping: plain if safe, else quoted
    (by-path devices contain ':')."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value)
    if text.isdigit() or all(c.isalnum() or c in "_./-" for c in text):
        return text
    return json.dumps(text, ensure_ascii=False)


def _cameras_arg(arm: dict, cfg: dict) -> str:
    parts = []
    for policy_cam, physical in arm["cameras"].items():
        camera = cfg["cameras"][physical]
        extra = dict(camera) if isinstance(camera, dict) else {"path": camera}
        device = extra.pop("path")
        fields = {
            "type": extra.pop("type", "opencv"),
            "index_or_path": device,
            "width": extra.pop("width", cfg["camera_width"]),
            "height": extra.pop("height", cfg["camera_height"]),
            "fps": extra.pop("fps", cfg["fps"]),
            **extra,  # e.g. fourcc, rotation
        }
        inner = ", ".join(f"{k}: {_yaml_scalar(v)}" for k, v in fields.items())
        parts.append(f"{policy_cam}: {{{inner}}}")
    return "{ " + ", ".join(parts) + " }"


def _number(value) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() else str(value)


def _new_dataset_root(policy_id: str) -> str:
    """A folder that doesn't exist yet: LeRobotDataset.create() refuses an
    existing root, so reusing one fixed --dataset.root fails from run two."""
    base = os.path.join(_require_cfg()["dataset_root_dir"],
                        f"{policy_id}_{datetime.now():%Y%m%d_%H%M%S}")
    root, n = base, 2
    while os.path.exists(root):
        root, n = f"{base}_{n}", n + 1
    return root


def build_command(policy_id: str, entry: dict) -> list:
    """The lerobot-rollout argv for one policy run."""
    cfg = _require_cfg()
    arm = cfg["arms"][entry["arm"]]
    fps = cfg["fps"]
    seconds = _number(entry["execution_seconds"])
    # draccus YAML-parses string values: "a: b" would become a dict and
    # "yes" a bool, so the task is passed quoted
    task = json.dumps(entry["task_instruction"], ensure_ascii=False)

    command = [
        _rollout_bin() or "lerobot-rollout",
        f"--strategy.type={cfg['strategy']}",
        f"--robot.type={cfg['robot_type']}",
        f"--robot.port={arm['port']}",
        f"--robot.id={arm['id']}",
        f"--robot.cameras={_cameras_arg(arm, cfg)}",
        f"--display_data={'true' if cfg['display_data'] else 'false'}",
    ]
    if cfg["strategy"] == "episodic":
        command += [
            f"--dataset.repo_id={cfg['dataset_user']}/rollout_{policy_id}",
            f"--dataset.root={_new_dataset_root(policy_id)}",
            f"--dataset.single_task={task}",
            "--dataset.num_episodes=1",
            f"--dataset.episode_time_s={seconds}",
            "--dataset.push_to_hub=false",
            f"--policy.path={entry['policy_path']}",
            f"--dataset.fps={fps}",
        ]
    else:  # base: no recording, runs for --duration
        command += [
            f"--task={task}",
            f"--duration={seconds}",
            f"--policy.path={entry['policy_path']}",
        ]
    command.append(f"--fps={fps}")
    command += cfg["extra_args"] + entry["extra_args"]
    return command


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------

def _failure_hint(result, entry: dict) -> str:
    arm = _require_cfg()["arms"].get(entry["arm"], {})
    if _CALIBRATION_PROMPT in result.seen:
        return (f" lerobot-rollout stopped to ask about calibration: the motors on "
                f"{arm.get('port')} don't match {arm.get('id')}.json. Check that port really is "
                f"the {entry['arm']} arm's board. If it is and this happens after every drive "
                f"(the route scripts write their own calibration), set "
                f"auto_confirm_calibration: true in {config.ROLLOUT_FILE}.")
    if _CAMERA_MISMATCH in result.seen:
        return (f" The camera names for arm '{entry['arm']}' in {config.ROLLOUT_FILE} don't "
                f"match the names this policy was trained with.")
    return ""


def execute_policy(policy_id: str, policies: dict) -> bool:
    """
    Runs the policy identified by policy_id on its arm and blocks until it
    has finished and released the arm -- the robot's stop at this place.

    Returns True if the policy ran (or was dry-run), False if it was
    skipped: no policies loaded (--no-policies) or no policy_path set.
    Raises if the policy_id is unknown or the rollout fails or times out;
    job_service.py turns that into a failed job.
    """
    log_event("execute_policy_called", policy_id=policy_id)

    if not policies:
        log_event("null_policies", policy_id=policy_id)
        return False

    entry = policies.get(policy_id)
    if entry is None:
        raise ValueError(f"No policy found for policy_id '{policy_id}' — check {config.POLICIES_FILE}")

    if not entry["policy_path"]:
        print(f"[policy] '{policy_id}' has no policy_path in {config.POLICIES_FILE} -- skipping")
        log_event("policy_skipped_not_configured", policy_id=policy_id)
        return False

    command = build_command(policy_id, entry)
    seconds = float(entry["execution_seconds"])
    arm = _require_cfg()["arms"][entry["arm"]]

    log_event("policy_start", policy_id=policy_id, arm=entry["arm"], port=arm["port"],
              execution_seconds=_number(seconds), dry_run=_dry_run)
    print(f"[policy] {policy_id} on {entry['arm']} arm for {_number(seconds)}s:\n"
          f"  {shlex.join(command)}", flush=True)

    if _dry_run:
        time.sleep(_dry_run_pause)
        log_event("policy_complete", policy_id=policy_id, dry_run=True)
        return True

    log_path = os.path.join(config.LOG_DIR, f"rollout_{policy_id}_{datetime.now():%Y-%m-%d_%H-%M-%S}.log")
    result = hw_process.run(
        command,
        label=f"policy:{policy_id}",
        timeout_s=seconds + config.POLICY_TIMEOUT_MARGIN_SECONDS,
        grace_s=config.POLICY_SIGINT_GRACE_SECONDS,
        # One Enter answers lerobot's "use the calibration file?" prompt, like
        # robot_core's AutoEnterStream does for the route scripts. Off: stdin
        # is /dev/null, so that prompt fails the policy instead of hanging.
        stdin="\n" if _require_cfg()["auto_confirm_calibration"] else None,
        tail_lines=config.POLICY_OUTPUT_TAIL_LINES,
        log_path=log_path,
        watch=(_CALIBRATION_PROMPT, _CAMERA_MISMATCH),
    )

    if result.timed_out:
        raise RuntimeError(
            f"policy '{policy_id}' did not finish within "
            f"{_number(seconds + config.POLICY_TIMEOUT_MARGIN_SECONDS)}s and was stopped "
            f"(full output: {log_path})"
        )

    if result.returncode != 0:
        detail = " / ".join(result.tail) if result.tail else "no output"
        raise RuntimeError(
            f"policy '{policy_id}' (lerobot-rollout) exited with code {result.returncode}."
            f"{_failure_hint(result, entry)} Last output: {detail} (full output: {log_path})"
        )

    log_event("policy_complete", policy_id=policy_id, output_log=log_path)
    return True
