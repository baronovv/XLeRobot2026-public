# Training Policies with Arm-Only Data Collection

## Install 

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

```
pip install 'lerobot[training]'
pip install 'lerobot[pi]'
pip install 'lerobot[xvla]'
```

* Install additional libraries:

Needed by SmolVLA:

```
pip install num2words
```

## Train ACT Policy

```
lerobot-train \
  --dataset.repo_id=right-arm-test \
  --dataset.root=/home/jetson8/datasets/right_arm_test \
  --policy.type=act \
  --output_dir=outputs/train/act_right_arm \
  --job_name=act_right_arm_training \
  --policy.device=cuda \
  --steps=10000 \
  --batch_size=8 \
  --log_freq=200 \
  --save_freq=2000 \
  --policy.push_to_hub=false \
  --wandb.enable=true
```

Training it with larger image backbone:

```
# ResNet-34
--policy.vision_backbone=resnet34 \
--policy.pretrained_backbone_weights=ResNet34_Weights.IMAGENET1K_V1 \

# ResNet-50
--policy.vision_backbone=resnet50 \
--policy.pretrained_backbone_weights=ResNet50_Weights.IMAGENET1K_V1 \

```

## Train XVLA Policy

```
# XVLA — with rename_map for the camera-key mismatch
lerobot-train \
  --dataset.repo_id=right-arm-test \
  --dataset.root=/home/jetson8/datasets/right_arm_test \
  --policy.path=lerobot/xvla-base \
  --policy.action_mode=auto \
  --policy.dtype=bfloat16 \
  --policy.freeze_vision_encoder=false \
  --policy.freeze_language_encoder=false \
  --policy.train_policy_transformer=true \
  --policy.train_soft_prompts=true \
  --rename_map='{"observation.images.head": "observation.images.image"}' \
  --output_dir=outputs/train/xvla_right_arm \
  --job_name=xvla_right_arm_training \
  --policy.device=cuda \
  --steps=10000 \
  --batch_size=8 \
  --log_freq=200 \
  --save_freq=2000 \
  --policy.push_to_hub=false \
  --wandb.enable=true
```



## Train SmolVLA Policy

```
lerobot-train \
  --dataset.repo_id=right-arm-test \
  --dataset.root=/home/jetson8/datasets/right_arm_test \
  --policy.path=lerobot/smolvla_base \
  --policy.freeze_vision_encoder=true \
  --policy.train_expert_only=true \
  --policy.train_state_proj=true \
  --rename_map='{"observation.images.head": "observation.images.camera1"}' \
  --output_dir=outputs/train/smolvla_right_arm \
  --job_name=smolvla_right_arm_training \
  --policy.device=cuda \
  --steps=5000 \
  --batch_size=8 \
  --log_freq=200 \
  --save_freq=5000 \
  --policy.push_to_hub=false \
  --wandb.enable=true
```

## Train pi0 Policy

*Note: This made my computer freeze and could not be executed. Maybe start with batch_size=1 and increase if your machine can take the load.*

```
lerobot-train \
  --dataset.repo_id=right-arm-test \
  --dataset.root=/home/jetson8/datasets/right_arm_test \
  --policy.path=lerobot/pi0_base \
  --policy.dtype=bfloat16 \
  --policy.freeze_vision_encoder=false \
  --policy.train_expert_only=false \
  --rename_map='{"observation.images.head": "observation.images.base_0_rgb"}' \
  --output_dir=outputs/train/pi0_right_arm \
  --job_name=pi0_right_arm_training \
  --policy.device=cuda \
  --steps=10000 \
  --batch_size=1 \
  --log_freq=200 \
  --save_freq=2000 \
  --policy.push_to_hub=false \
  --wandb.enable=true
```