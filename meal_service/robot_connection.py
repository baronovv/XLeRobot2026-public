"""
robot_connection.py — connects to the right robot class per policy,
reusing the same two physical ports across robot kinds.

Handles right_arm / left_arm / bimanual only (so101_follower /
bi_so_follower), native to the lerobot==0.6.0 install this app runs
under. xlerobot (full base + arms, for navigation) is intentionally
NOT handled here yet -- it lives in a separate, incompatible lerobot
fork (0.4.1, at /home/jetson8/lerobot/src), and wiring it in needs a
bridge process, not a direct import.

Policies run one at a time. Each was trained against a specific
robot.type using the same two physical ports, just wired up
differently. get_robot(robot_kind, camera_keys) keeps at most one
connection open -- if the requested robot_kind OR camera set differs
from whatever's currently connected, the old one is disconnected
first, since both target the same underlying serial ports.

Cameras are shared across all robot_kinds (same physical cameras
regardless of which arm connection is active), so they're read once
from robot.yml's top-level "cameras" key. camera_keys lets a caller
(policies.py) open only the subset a given policy actually declares,
even though robot.yml can define more than that.
"""
import yaml

import config

_SUPPORTED_KINDS = ("right_arm", "left_arm", "bimanual")

_robot = None
_robot_kind = None
_robot_cameras = None  # frozenset of camera keys currently connected


def _build_camera_configs(cameras_data: dict) -> dict:
    from lerobot.cameras.opencv import OpenCVCameraConfig

    built = {}
    for name, cam in cameras_data.items():
        cam_type = cam.get("type", "opencv")
        if cam_type != "opencv":
            raise ValueError(f"Camera '{name}': unsupported camera type '{cam_type}' (only 'opencv' is wired up)")
        built[name] = OpenCVCameraConfig(
            index_or_path=cam["index_or_path"],
            width=cam["width"],
            height=cam["height"],
            fps=cam["fps"],
        )
    return built


def disconnect_robot() -> None:
    """
    Force-closes the cached connection and clears the cache state, so the
    next get_robot() call reconnects fresh rather than handing back an
    already-disconnected object.

    Called by policies.py when a policy run fails -- the connection may be
    in an undefined state at that point, so reuse is not safe. Safe to
    call when nothing is connected.
    """
    global _robot, _robot_kind, _robot_cameras

    if _robot is not None:
        try:
            _robot.disconnect()
        except Exception:
            pass  # already failing; don't mask the original exception

    _robot = None
    _robot_kind = None
    _robot_cameras = None


def get_robot(robot_kind: str, camera_keys=None):
    global _robot, _robot_kind, _robot_cameras

    if robot_kind not in _SUPPORTED_KINDS:
        raise ValueError(
            f"robot_kind '{robot_kind}' is not supported. Supported: {_SUPPORTED_KINDS}. "
            "(xlerobot is deferred until the navigation bridge exists.)"
        )

    with open(config.ROBOT_FILE, "r") as f:
        data = yaml.safe_load(f)

    available_cameras = data["cameras"]
    if camera_keys is None:
        camera_keys = set(available_cameras.keys())
    camera_keys = frozenset(camera_keys)

    unknown = camera_keys - set(available_cameras.keys())
    if unknown:
        raise ValueError(
            f"Requested camera(s) {unknown} not defined in robot.yml. "
            f"Available: {set(available_cameras.keys())}"
        )

    if _robot is not None and _robot_kind == robot_kind and _robot_cameras == camera_keys:
        return _robot

    if _robot is not None:
        _robot.disconnect()
        _robot = None
        _robot_kind = None
        _robot_cameras = None

    ports = data["ports"]
    cameras_subset = {k: v for k, v in available_cameras.items() if k in camera_keys}
    cameras = _build_camera_configs(cameras_subset)
    kind_cfg = data["robots"][robot_kind]

    if robot_kind in ("right_arm", "left_arm"):
        from lerobot.robots.so_follower import SOFollower, SO101FollowerConfig
        port = ports["port2"] if robot_kind == "right_arm" else ports["port1"]
        robot_config = SO101FollowerConfig(
            port=port,
            id=kind_cfg["id"],
            max_relative_target=kind_cfg.get("max_relative_target"),
            cameras=cameras,
        )
        robot = SOFollower(robot_config)

    elif robot_kind == "bimanual":
        from lerobot.robots.bi_so_follower import BiSOFollower, BiSOFollowerConfig
        from lerobot.robots.so_follower import SOFollowerConfig as ArmCfg
        robot_config = BiSOFollowerConfig(
            id=kind_cfg["id"],
            left_arm_config=ArmCfg(port=ports["port1"], max_relative_target=kind_cfg.get("max_relative_target")),
            right_arm_config=ArmCfg(port=ports["port2"], max_relative_target=kind_cfg.get("max_relative_target")),
            cameras=cameras,
        )
        robot = BiSOFollower(robot_config)

    try:
        robot.connect()
    except Exception:
        try:
            robot.disconnect()
        except Exception:
            pass
        raise

    _robot = robot
    _robot_kind = robot_kind
    _robot_cameras = camera_keys
    return robot