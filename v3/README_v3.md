# Arms-Only Teleoperation

This version does teleoperation for arms only, not the whole XLeRobot setup. It uses the latest LeRobot framework (0.6.0).

## Install LeRobot

* Create Conda environment:

```
conda create -y -n lerobot python=3.12
conda activate lerobot
```

* Install ffmpeg:

```
conda install ffmpeg=7.1.1 -c conda-forge
```

* Install LeRobot: 

```
pip install lerobot=0.6.0
```

* Install LeRobot additional functions:

    * For Jetson (data recording, replay, calibration):

    ```
    pip install 'lerobot[feetech]'
    pip install 'lerobot[core_scripts]'
    ```

    * For the computers on which only training will be done:

    ```
    pip install 'lerobot[training]'
    ```

    * Policies:

    ```
    pip install 'lerobot[pi]'
    pip install 'lerobot[xvla]'
    pip install 'lerobot[smolvla]'
    ```

    * Documentation: see the [LeRobot documentation](https://huggingface.co/docs/lerobot/installation) for more information of what each of these means.


## Port / ID Conventions

* Single arm: `so101_follower` (robot) / `so101_leader` (teleop).
* Bimanual: `bi_so_follower` (robot) / `bi_so_leader` (teleop). Per-arm settings are passed through nested `left_arm_config.*` / `right_arm_config.*` arguments; there's a single top-level `--robot.id` / `--teleop.id`, and each arm's own id is derived automatically as `<id>_left` / `<id>_right` (that's also what its calibration file is saved/loaded as).

| Role                    | Port             | ID                  |
|--------------------------|------------------|---------------------|
| Left arm (follower)      | `/dev/ttyACM0`   | `left_arm`          |
| Right arm (follower)     | `/dev/ttyACM1`   | `right_arm`         |
| Left arm (leader)        | `/dev/ttyACM2`   | `left_arm_leader`   |
| Right arm (leader)       | `/dev/ttyACM3`   | `right_arm_leader`  |

Adjust ports to whatever your arms actually enumerate as — run `lerobot-find-port` if unsure.



---

# Single-Arm Setup

## Calibration

Calibrate the follower first, then the leader. Run each once, before first use or after any reassembly.

```bash
# Follower
lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM1 \
  --robot.id=right_arm
```

```bash
# Leader
lerobot-calibrate \
  --teleop.type=so101_leader \
  --teleop.port=/dev/ttyACM3 \
  --teleop.id=right_arm_leader
```

Swap the port/id to `left_arm` / `/dev/ttyACM0` (follower) and `left_arm_leader` / `/dev/ttyACM2` (leader) for the left arm.

## Teleoperation

```bash
lerobot-teleoperate \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM1 \
  --robot.id=right_arm \
  --teleop.type=so101_leader \
  --teleop.port=/dev/ttyACM3 \
  --teleop.id=right_arm_leader \
  --display_data=true
```

Swap the ports/ids to `left_arm` / `left_arm_leader` / `/dev/ttyACM0` / `/dev/ttyACM2` to run the left arm instead.

## Data Collection

```bash
rm -rf /home/jetson8/datasets/right_arm_test && lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM1 \
  --robot.id=right_arm \
  --robot.max_relative_target=50.0 \
  --robot.cameras="{ head: {type: opencv, index_or_path: /dev/video8, width: 640, height: 480, fps: 30}, left: {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30}, right: {type: opencv, index_or_path: /dev/video0, width: 640, height: 480, fps: 30} }" \
  --teleop.type=so101_leader \
  --teleop.port=/dev/ttyACM3 \
  --teleop.id=right_arm_leader \
  --display_data=false \
  --dataset.repo_id=right-arm-test \
  --dataset.root=/home/jetson8/datasets/right_arm_test \
  --dataset.single_task="Describe the task here" \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=10 \
  --dataset.push_to_hub=false
```

Adjust `--robot.cameras` to match your actual camera devices, and adjust ports/ids to `left_arm` / `left_arm_leader` for the left-arm-only dataset.

## Policy Evaluation

### Using lerobot-rollout

```bash
lerobot-rollout \
  --strategy.type=episodic \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM1 \
  --robot.id=right_arm \
  --robot.max_relative_target=50.0 \
  --robot.cameras="{ head: {type: opencv, index_or_path: /dev/video8, width: 640, height: 480, fps: 30}, left: {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30}, right: {type: opencv, index_or_path: /dev/video0, width: 640, height: 480, fps: 30} }" \
  --display_data=true \
  --policy.path=outputs/train/act_right_arm_test_move_banana/checkpoints/last/pretrained_model \
  --dataset.repo_id=rollout_act_right_arm_test_move_banana \
  --dataset.root=/home/jetson8/datasets/act_right_arm_test_move_banana \
  --dataset.single_task="Move the banana to the plate" \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=15 \
  --dataset.reset_time_s=5 \
  --dataset.push_to_hub=false
```

`--policy.path` accepts either a Hugging Face Hub repo id or a local checkpoint directory (e.g. `outputs/train/act_right_arm/checkpoints/last/pretrained_model`). Keep `--robot.id` identical to whatever was used during data collection/training so calibration and camera key names line up correctly.


### Using lerobot-record

Evaluation reuses `lerobot-record` with a trained policy in place of the teleop leader — the policy drives the follower directly, and the resulting rollouts are (optionally) saved as an eval dataset. No `--teleop.*` flags are passed.

```bash
lerobot-record \
  --robot.type=so101_follower \
  --robot.port=/dev/ttyACM1 \
  --robot.id=right_arm \
  --robot.cameras="{ head: {type: opencv, index_or_path: /dev/video8, width: 640, height: 480, fps: 30}, left: {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30}, right: {type: opencv, index_or_path: /dev/video0, width: 640, height: 480, fps: 30} }" \
  --display_data=false \
  --dataset.repo_id=right-arm-eval \
  --dataset.root=/home/jetson8/datasets/right_arm_eval \
  --dataset.single_task="Describe the task here" \
  --dataset.num_episodes=1 \
  --dataset.push_to_hub=false \
  --policy.path=my_trained_policy
```

`--policy.path` accepts either a Hugging Face Hub repo id or a local checkpoint directory (e.g. `outputs/train/act_right_arm/checkpoints/last/pretrained_model`). Keep `--robot.id` identical to whatever was used during data collection/training so calibration and camera key names line up correctly.




---

# Dual Arm (Bimanual) Setup. UNTESTED!

## Calibration

One `lerobot-calibrate` call per device (follower, leader) calibrates both arms in sequence — left arm first, then right. Per-arm calibration files are saved automatically as `<id>_left` / `<id>_right`.

```bash
# Bimanual follower (calibrates left arm, then right arm)
lerobot-calibrate \
  --robot.type=bi_so_follower \
  --robot.id=bimanual_follower \
  --robot.left_arm_config.port=/dev/ttyACM0 \
  --robot.right_arm_config.port=/dev/ttyACM1
```

```bash
# Bimanual leader (calibrates left arm, then right arm)
lerobot-calibrate \
  --teleop.type=bi_so_leader \
  --teleop.id=bimanual_leader \
  --teleop.left_arm_config.port=/dev/ttyACM2 \
  --teleop.right_arm_config.port=/dev/ttyACM3
```

## Teleoperation

```bash
lerobot-teleoperate \
  --robot.type=bi_so_follower \
  --robot.id=bimanual_follower \
  --robot.left_arm_config.port=/dev/ttyACM0 \
  --robot.left_arm_config.max_relative_target=50.0 \
  --robot.right_arm_config.port=/dev/ttyACM1 \
  --robot.right_arm_config.max_relative_target=50.0 \
  --teleop.type=bi_so_leader \
  --teleop.id=bimanual_leader \
  --teleop.left_arm_config.port=/dev/ttyACM2 \
  --teleop.right_arm_config.port=/dev/ttyACM3 \
  --display_data=true
```

## Data Collection

Cameras are declared once as a flat dict on `--robot.cameras` (not split per arm) — same `head` / `left` / `right` layout as the single-arm setup.

```bash
rm -rf /home/jetson8/datasets/bimanual_test && lerobot-record \
  --robot.type=bi_so_follower \
  --robot.id=bimanual_follower \
  --robot.left_arm_config.port=/dev/ttyACM0 \
  --robot.left_arm_config.max_relative_target=50.0 \
  --robot.right_arm_config.port=/dev/ttyACM1 \
  --robot.right_arm_config.max_relative_target=50.0 \
  --robot.cameras="{ head: {type: opencv, index_or_path: /dev/video8, width: 640, height: 480, fps: 30}, left: {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30}, right: {type: opencv, index_or_path: /dev/video0, width: 640, height: 480, fps: 30} }" \
  --teleop.type=bi_so_leader \
  --teleop.id=bimanual_leader \
  --teleop.left_arm_config.port=/dev/ttyACM2 \
  --teleop.right_arm_config.port=/dev/ttyACM3 \
  --display_data=false \
  --dataset.repo_id=bimanual-test \
  --dataset.root=/home/jetson8/datasets/bimanual_test \
  --dataset.single_task="Describe the bimanual task here" \
  --dataset.num_episodes=10 \
  --dataset.episode_time_s=30 \
  --dataset.reset_time_s=10 \
  --dataset.push_to_hub=false
```

Adjust `--robot.cameras` to match your actual camera devices.

## Policy Evaluation

Evaluation reuses `lerobot-record` with a trained policy in place of the teleop leader — the policy drives both arms directly. No `--teleop.*` flags are passed.

```bash
lerobot-record \
  --robot.type=bi_so_follower \
  --robot.id=bimanual_follower \
  --robot.left_arm_config.port=/dev/ttyACM0 \
  --robot.right_arm_config.port=/dev/ttyACM1 \
  --robot.cameras="{ head: {type: opencv, index_or_path: /dev/video8, width: 640, height: 480, fps: 30}, left: {type: opencv, index_or_path: /dev/video10, width: 640, height: 480, fps: 30}, right: {type: opencv, index_or_path: /dev/video0, width: 640, height: 480, fps: 30} }" \
  --display_data=false \
  --dataset.repo_id=bimanual-eval \
  --dataset.root=/home/jetson8/datasets/bimanual_eval \
  --dataset.single_task="Describe the bimanual task here" \
  --dataset.num_episodes=1 \
  --dataset.push_to_hub=false \
  --policy.path=my_trained_bimanual_policy
```

`--policy.path` accepts either a Hugging Face Hub repo id or a local checkpoint directory (e.g. `outputs/train/act_bimanual/checkpoints/last/pretrained_model`). Keep `--robot.id` identical to whatever was used during data collection/training so calibration and camera key names line up correctly.

---

# Policy Training

See `v3/TRAIN_v3.md` for training instructions.






