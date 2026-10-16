# Training


## Install 

```
pip install num2words
pip install tiktoken
```

## ACT

### Train the ACT policy:

```
HF_HUB_OFFLINE=1 python -m lerobot.scripts.lerobot_train \
  --dataset.repo_id=xlerobot_repo/test_teleop_success_1 \
  --dataset.root=/Users/mihaylt1/Projects/xlerobot/data/test_teleop_success_1_repaired \
  --policy.type=act \
  --output_dir=/Users/mihaylt1/Projects/xlerobot/policies/act_test_teleop \
  --job_name=act_test_teleop \
  --policy.device=cuda \
  --wandb.enable=true \
  --policy.repo_id=xlerobot_repo/act_test_teleop \
  --steps=100 \
  --log_freq=10 \
  --save_freq=50 \
  --policy.push_to_hub=false \
  2> >(grep -v '^objc\[' >&2)
```

With larger image backbone, for better policy: 

```
HF_HUB_OFFLINE=1 python -m lerobot.scripts.lerobot_train \
  --dataset.repo_id=xlerobot_repo/test_teleop_success_1 \
  --dataset.root=/Users/mihaylt1/Projects/xlerobot/data/test_teleop_success_1_repaired \
  --policy.type=act \
  --policy.vision_backbone=resnet34 \
  --policy.pretrained_backbone_weights=ResNet34_Weights.IMAGENET1K_V1 \
  --output_dir=/Users/mihaylt1/Projects/xlerobot/policies/act34_test_teleop \
  --job_name=act34_test_teleop \
  --policy.device=cuda \
  --wandb.enable=true \
  --policy.repo_id=xlerobot_repo/act34_test_teleop \
  --steps=100 \
  --log_freq=10 \
  --save_freq=50 \
  --policy.push_to_hub=false \
  2> >(grep -v '^objc\[' >&2)
```

```
HF_HUB_OFFLINE=1 python -m lerobot.scripts.lerobot_train \
  --dataset.repo_id=xlerobot_repo/test_teleop_success_1 \
  --dataset.root=/Users/mihaylt1/Projects/xlerobot/data/test_teleop_success_1_repaired \
  --policy.type=act \
  --policy.vision_backbone=resnet34 \
  --policy.pretrained_backbone_weights=ResNet34_Weights.IMAGENET1K_V1 \
  --output_dir=/Users/mihaylt1/Projects/xlerobot/policies/act50_test_teleop \
  --job_name=act50_test_teleop \
  --policy.device=cuda \
  --wandb.enable=true \
  --policy.repo_id=xlerobot_repo/act50_test_teleop \
  --steps=100 \
  --log_freq=10 \
  --save_freq=50 \
  --policy.push_to_hub=false \
  2> >(grep -v '^objc\[' >&2)
```

### Execute the trained ACT policy:

```
python -m lerobot.record \
  --robot.type=xlerobot \
  --robot.port1=/dev/ttyACM1 \
  --robot.port2=/dev/ttyACM0 \
  --robot.id=xlerobot_pi \
  --robot.max_relative_target=15.0 \
  --robot.cameras="{ head: {type: opencv, index_or_path: '/dev/v4l/by-id/usb-Orbbec_R__Orbbec_Gemini_335_CP0F4630004K-video-index0', width: 640, height: 480, fps: 15}, left: {type: opencv, index_or_path: '/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._USB2.0_CAM1_USB2.0_CAM1-video-index0', width: 640, height: 480, fps: 15}, right: {type: opencv, index_or_path: '/dev/v4l/by-id/usb-HBVCAM_Camera_Autodarts_DIY_Cam_HB20250300001-video-index0', width: 640, height: 480, fps: 15} }" \
  --policy.path=/home/jetson8/xlerobot/policies/act_test_teleop_smoke/checkpoints/last/pretrained_model \
  --policy.device=mps \
  --dataset.repo_id=ktotomama/eval_act_test_teleop \
  --dataset.single_task="Test teleop." \
  --dataset.root=/home/jetson8/datasets/eval_act_test_teleop \
  --display_data=true \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30
```


## SmolVLA

### Train the SmolVLA policy:

```
python -m lerobot.scripts.lerobot_train \
  --dataset.repo_id=xlerobot_repo/test_teleop_success_1 \
  --dataset.root=/Users/mihaylt1/Projects/xlerobot/data/test_teleop_success_1_repaired \
  --policy.type=smolvla \
  --policy.pretrained_path=lerobot/smolvla_base \
  --policy.repo_id=xlerobot_repo/smolvla_finetune \
  --output_dir=/Users/mihaylt1/Projects/xlerobot/policies/smolvla_test_teleop \
  --job_name=smolvla_test_teleop \
  --policy.device=mps \
  --policy.dtype=bfloat16 \
  --policy.push_to_hub=false \
  --wandb.enable=true \
  --steps=100 \
  --log_freq=10 \
  --save_freq=50 \
  --batch_size=8
```

### Execute the trained SmolVLA policy:

```
python -m lerobot.record \
  --robot.type=xlerobot \
  --robot.port1=/dev/ttyACM1 \
  --robot.port2=/dev/ttyACM0 \
  --robot.id=xlerobot_pi \
  --robot.max_relative_target=15.0 \
  --robot.cameras="{ head: {type: opencv, index_or_path: '/dev/v4l/by-id/usb-Orbbec_R__Orbbec_Gemini_335_CP0F4630004K-video-index0', width: 640, height: 480, fps: 15}, left: {type: opencv, index_or_path: '/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._USB2.0_CAM1_USB2.0_CAM1-video-index0', width: 640, height: 480, fps: 15}, right: {type: opencv, index_or_path: '/dev/v4l/by-id/usb-HBVCAM_Camera_Autodarts_DIY_Cam_HB20250300001-video-index0', width: 640, height: 480, fps: 15} }" \
  --policy.path=/home/jetson8/xlerobot/policies/smolvla_test_teleop/checkpoints/last/pretrained_model \
  --policy.device=mps \
  --dataset.repo_id=ktotomama/eval_smolvla_test_teleop \
  --dataset.single_task="Test teleop." \
  --dataset.root=/home/jetson8/datasets/eval_smolvla_test_teleop \
  --display_data=true \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=30
```
