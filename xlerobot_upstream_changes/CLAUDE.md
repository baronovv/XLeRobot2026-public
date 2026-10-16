# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

XLeRobot is an open-source, low-cost (~$660) dual-arm mobile household robot built on top of the HuggingFace [LeRobot](https://github.com/huggingface/lerobot) framework, SO-100/SO-101 arms, and LeKiwi. This is a monorepo combining hardware designs, real-robot control code, simulations, a web control stack, and VR teleoperation. There is no top-level build system or test suite; each subdirectory is largely self-contained.

Docs live at https://xlerobot.readthedocs.io. Contribution focus is software (CV, navigation, sim, VLA/RL, UIs) — the hardware design is settled (see CONTRIBUTING.md).

## Architecture

### `software/` — real-robot control (LeRobot overlay)

This directory **mirrors the lerobot package layout and is not runnable in place**. The intended workflow (docs/en/source/software/getting_started/install.md) is: install lerobot with `pip install -e .`, then copy files into it:
- `software/src/model/SO101Robot.py` (analytical IK solver) → lerobot's `/model` folder
- `software/src/robots/xlerobot*` → lerobot's `/robots` folder
- `software/examples/*` → lerobot's `/examples` folder

Imports in the examples therefore reference `lerobot.robots.xlerobot`, `lerobot.model.SO101Robot`, etc. Example script headers show run commands, e.g.:
```bash
PYTHONPATH=src python -m lerobot.robots.xlerobot.xlerobot_host --robot.id=my_xlerobot   # on the robot host
```

- Robot variants: `xlerobot` (omni-wheel), `xlerobot_2wheels` (differential), `xlerobot_mecanum` — each under `software/src/robots/`.
- Host/client split (`xlerobot_host.py` / `xlerobot_client.py`) is for Raspberry Pi setups over ZeroMQ; these are commented out in `__init__.py` by default — uncomment for Pi builds.
- Examples are numbered by progression: 0 = keyboard joint control, 1–2 = keyboard EE control (single/dual arm, analytical IK), 3 = YOLO vision control, 4 = full XLeRobot keyboard teleop, 5 = Xbox controller, 6–7 = Switch Joycon, 8 = VR teleop (+ dataset recording).

### `XLeVR/` — VR (Quest) teleoperation

Standalone, minimal refactor of telegrip. Serves a web UI to the headset browser over HTTPS (port 8443) and receives controller data over WebSocket (port 8442). `config.yaml` holds ports and arm serial devices (`/dev/ttySO100red`, `/dev/ttySO100blue`). The `VRMonitor` class exposes `ControlGoal` objects (`arm`, `mode`, `target_position`, `wrist_roll_deg`, `wrist_flex_deg`, `gripper_closed`, `metadata`) via `get_left_goal_nowait()` / `get_right_goal_nowait()` — this is the API the teleop examples consume.

```bash
cd XLeVR && pip install -r requirements.txt && python vr_monitor.py
```

### `web_control/` — browser control stack

- `server/`: FastAPI + Socket.IO + uvicorn (Python 3.11+). Configured via `.env` (`UI_HOST`, `UI_PORT`, `ROBOT_HOST`, `ROBOT_PORT_CMD=5555`, `ROBOT_PORT_DATA=5556`). Talks to the robot over ZeroMQ; `core/remote_core.py` is the control hub, `api/streaming.py` handles video.
- `client/`: React 19 + TypeScript + Vite + Tailwind 4, socket.io-client.

```bash
# server
cd web_control/server && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env && python main.py

# client
cd web_control/client && npm install
npm run dev      # dev server (http://localhost:5173)
npm run build    # tsc -b && vite build
npm run lint     # eslint
```

### `simulation/`

- `mujoco/`: keyboard-controlled sim (`mujoco==3.3.0`). `xlerobot.xml` / `scene.xml` are the models.
  ```bash
  cd simulation/mujoco && pip install -r requirements.txt && python xlerobot_mujoco.py
  ```
- `Maniskill/`: XLeRobot agents/envs for ManiSkill (SAPIEN). `run_xlerobot_sim.py` registers local `agents/` then launches. Using XLeRobot in ReplicaCAD scenes requires registering the robot id in the scene config and ManiSkill's agents `__init__.py` (see `simulation/Maniskill/readme.md`), then pass `-r "xlerobot_single"` etc.
- `Isaac_sim/`: assets zip only.

### `docs/` — Sphinx site (readthedocs)

```bash
cd docs && pip install -r requirements.txt && make html
sphinx-autobuild ./source ./build/html   # live rebuild
```

Some pages are **auto-generated** by `docs/generate_robot_docs.py` / `generate_task_docs.py` — files carrying the `THIS IS ALL GENERATED DOCUMENTATION` header comment must not be edited directly. English docs in `docs/en/source`, Chinese in `docs/zh`.

### `hardware/`

STL/STEP files and bills of materials for the 3D-printed parts and variants. Not code.
