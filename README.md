
Final code for the **Summer Robotics Challenge 2026**. An XLeRobot (two SO-101 arms on a LeKiwi omni-wheel base, Jetson Orin Nano) performs a simplified version of a nursing-home task: it takes meal orders from a cloud admin panel, drives to the kitchen, places the food on a tray with learned manipulation policies, delivers it to the resident's table and returns to base.

Final state is tagged `srx2026-final`. The previous `main` is tagged `pre-final-main`.

---

## How it works

```
cloud admin panel ──poll──▶ meal_service (job loop)
                                │
          ┌─────────────────────┼──────────────────────┐
          ▼                     ▼                      ▼
   navigation.py          policies.py            api_client.py
   zone graph + BFS       lerobot-rollout        job status updates
   runs route scripts     per meal type / arm
          │
          ▼
   robotmovement/route_part{1,2,3}.py  (fixed driving legs)
```

One job runs: **base → place B (kitchen) → manipulation policy → place C (table) → manipulation policy → base**. Only one policy runs at a time, at each stop.

- **Job source:** `meal_service` polls `https://care-tray-admin.lovable.app` every 60 s for pending jobs and reports status back (`failed` is a valid status). The app exits after 120 s with no pending jobs.
- **Navigation:** `navigation.py` tracks the current zone, finds a path over the zone graph with BFS (`routes.yml` maps destinations to route legs), and launches each leg as a subprocess.
- **Manipulation:** each meal type has its own ACT checkpoint, run with the `lerobot-rollout` CLI (episodic strategy, `so101_follower`). Configured in `policies.yml` and `rollout.yml`.

---

## Repository layout

| Path | Contents |
|---|---|
| `meal_service/` | Main application: job loop, API client, navigation orchestration, policy runner, configs (`robot.yml`, `policies.yml`, `rollout.yml`, `routes.yml`, `locations.yml`) |
| `meal_service/policy_loaders/` | Loaders for ACT, Pi0, SmolVLA, X-VLA |
| `robotmovement/` | Route scripts for the three fixed driving legs, `robot_core.py`, and `pr.py` (exit-code patch for `robot_core.execute_route`) |
| `slam/` | RTAB-Map + Nav2 bring-up (`slam_up.sh`), wheel-odometry node (`lekiwi_base_node.py`), Nav2 params and launch file, bus/wheel test tools |
| `scripts/` | Development and hardware test scripts (motor scan, torque disable, turning, distance, ultrasonic, earlier route experiments) |
| `scripts/old_versions/` | Earlier copies of `robot_core.py` and route scripts. Use `robotmovement/` instead |
| `training/configs/` | `train_config.json` of trained ACT policies, for reproducing training |
| `datasets/README.md` | Links to all recorded datasets on Hugging Face |
| `xlerobot_upstream_changes/` | Local edits to upstream [XLeRobot](https://github.com/Vector-Wangel/XLeRobot) (`BASE.txt` = base commit, `modified_files.patch` + new files with paths kept) |
| `lerobot_upstream_changes/` | Local edits to upstream [LeRobot](https://github.com/huggingface/lerobot) `src/` as a patch, plus a list of all changed files |
| `v2/`, `v3/` | Earlier robot versions (v2: XLeRobot without head motors, 2 arms + LeKiwi base; v3: with SmolVLA policy install notes) |
| `TRAIN.md` | Training notes |

---

## Hardware

| Component | Details |
|---|---|
| Compute | Jetson Orin Nano (`jetson8`), Ubuntu 24.04, JetPack, aarch64 |
| Training machine | Desktop with RTX 4060 Ti 8 GB |
| Arms | 2× SO-101 follower, Feetech STS3215 servos |
| Motor boards | Board 1: left arm + head. Board 2: right arm + wheels (motors 7/8/9) |
| Base | LeKiwi, three omni wheels. Wheel radius 0.0425 m, effective base radius 0.1215 m |
| Cameras | Orbbec Gemini 335 (head/top), wrist camera |
| Teleop | Meta Quest 3 via XLeVR WebXR (WebSocket 8442, HTTPS 8443) |

**Always use stable device paths.** `/dev/ttyACMN` and `/dev/videoN` change between boots.

```bash
ls -l /dev/serial/by-path/    # motor boards
ls -l /dev/v4l/by-id/         # cameras
```

---

## Software setup

Two conda environments are needed because the route scripts and the app use incompatible LeRobot versions.

| Env | LeRobot | Used by |
|---|---|---|
| `lerobot060` | 0.6.0 | `meal_service`, `lerobot-rollout` inference |
| `lerobot` | 0.4.1, editable install from `~/lerobot/src` | route scripts (`robotmovement/`), called through `ROUTE_PYTHON` |

Other software: ROS 2 Jazzy, RTAB-Map 0.22.1, Nav2, pyorbbecsdk, XLeVR.

```bash
# 1. LeRobot 0.4.1 env for the route scripts
git clone https://github.com/huggingface/lerobot.git ~/lerobot
cd ~/lerobot && git checkout $(awk '{print $NF}' <repo>/lerobot_upstream_changes/BASE.txt)
git apply <repo>/lerobot_upstream_changes/local_changes.patch
conda create -n lerobot python=3.10 -y && conda activate lerobot
pip install -e ".[feetech]"

# 2. LeRobot 0.6.0 env for the app
conda create -n lerobot060 python=3.10 -y && conda activate lerobot060
pip install "lerobot[feetech]==0.6.0"

# 3. XLeRobot upstream with local changes
git clone https://github.com/Vector-Wangel/XLeRobot.git ~/XLeRobot
cd ~/XLeRobot && git checkout $(awk '{print $NF}' <repo>/xlerobot_upstream_changes/BASE.txt)
git apply <repo>/xlerobot_upstream_changes/modified_files.patch
rsync -av --exclude=BASE.txt --exclude='*.patch' <repo>/xlerobot_upstream_changes/ ~/XLeRobot/
```

### API key

The robot's admin-panel key is read from the environment. Never hardcode it in `config.py`.

```bash
echo 'export ROBOT_API_KEY="<key from admin panel>"' >> ~/.bashrc
```

If `meal_service` runs as a systemd service, set it with `Environment=ROBOT_API_KEY=...` in the unit file instead.

---

## Running

```bash
conda activate lerobot060
cd <repo>/meal_service
export ROUTE_PYTHON=$(conda run -n lerobot which python)

python main.py --no-policies --no-navigation   # job loop + API only
python main.py --no-policies                   # + driving, no arm policies
python main.py                                 # full pipeline
```

Bring the system up in this order: test each component on its own (cameras, each motor board, each arm), then the job loop, then navigation, then policies.

### Running a single policy by hand

```bash
conda activate lerobot060
lerobot-rollout --robot.type=so101_follower --robot.port=/dev/serial/by-path/<board> \
  --policy.path=<checkpoint>/pretrained_model --fps=<fps the dataset was recorded at> ...
```

Use a numbered checkpoint folder such as `checkpoints/030000/pretrained_model`. `checkpoints/last/` can be a broken symlink after copying.

### SLAM / Nav2 (separate track)

```bash
bash <repo>/slam/slam_up.sh
ros2 launch <repo>/slam/nav2/xlerobot_nav2.launch.py
```

The production map is an RTAB-Map database (`map_room_20260815_v3.db`, 169 nodes, 118 global loop closures). It is too large for git and is kept outside the repo. Localization works. The global costmap still marks too much as lethal (`track_unknown_space: true` plus obstacle height projection); the next things to try are a smaller inflation radius and `Grid/MaxObstacleHeight` = 0.30 m.

---

## Datasets and training

- Datasets: see [`datasets/README.md`](datasets/README.md), all hosted on Hugging Face under `ktotomama/`.
- Policy: ACT with a ResNet34 backbone (ResNet50 does not fit in 8 GB VRAM).
- Data: about 20 episodes per task at 30 fps. Episodes end with the gripper held open for 2–3 s after release; without this the policy did not learn to let go.
- Trained policies: three right-arm and two left-arm at the kitchen (place B), one left-arm and one right-arm at the table (place C). Each meal type has its own checkpoint folder, e.g. `act_right_arm_kulho/checkpoints/030000/pretrained_model`.
- Training configs: [`training/configs/`](training/configs/).

---

## Lessons learned

- **Feetech bus timing:** opening and closing the same motor bus with no pause hangs it. The app waits `ROUTE_SETTLE_SECONDS = 3` between route legs.
- **No SIGKILL during a bus transaction:** it corrupts bus state. Child processes get SIGINT and a 10 s grace period (`ROUTE_SIGINT_GRACE_SECONDS`).
- **Exit codes:** `robot_core.execute_route()` used to always return `None`, so failures were invisible. `robotmovement/pr.py` makes route scripts exit 1 on missing telemetry or a mid-mission exception, and 0 on success.
- **Camera keys must match training exactly.** Datasets used `top`/`wrist`. A rollout config with different names (`head`/`left`/`right`) fails silently or degrades.
- **Set `--fps` explicitly.** `lerobot-rollout` defaults to 30 fps, so a policy trained at 15 fps needs `--fps=15`.
- **`disable_torque_on_disconnect` defaults to `True`.** The arm drops whatever it holds when the connection closes. Handle this explicitly when carrying a plate between steps.
- **Never run route scripts in-process** with the app. They need the LeRobot 0.4.1 env.
- **Motor overload latch:** left-arm motors 2/3/4 can latch on overload. Recover with a full 12 V power cycle after moving the arm to a gravity-supported pose. A lit LED does not mean the servos are healthy (USB keeps the board powered).
- **Calibration IDs:** a new `--robot.id` creates a new calibration file. Reuse the existing ID or copy the file.
- **SmolVLA:** a diverging policy can push a joint into its limit and brown out the bus. Keep `max_relative_target` ≤ 10 and use few cameras.
- **RTAB-Map:** never copy `rtabmap.db` while the node is running. Wait for `Saving database...done!`, otherwise the copy is silently corrupted.

---

## Known open issues

- The cached arm connection in `robot_connection.get_robot()` can hold the serial port the route scripts need.
- It is not fully verified whether arm torque stays on between route legs (see `disable_torque_on_disconnect` above).
- The left arm on the second board has no calibration profile yet (`lerobot-calibrate --robot.id=my_left_arm`).
- Some seat and meal-slot IDs in `locations.yml` were not tested.
- `navigate_to()` logs the full locations dict on every call.
- The old API key exists in git history. Generate a new key in the admin panel before making this repository public.

## Workflow diagram  
<img width="960" height="540" alt="image" src="https://github.com/user-attachments/assets/07a7b049-2eab-43c5-b7cf-dad0cad68afd" />

