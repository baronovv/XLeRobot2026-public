# Teleoperation with Meta Quest

## Content
This folder contains two subfolders:
* `XLeRobot` - cloned from https://github.com/Vector-Wangel/XLeRobot
* `lerobot` - cloned from https://github.com/huggingface/lerobot/releases/tag/v0.4.1 

Then, the files that contain functionality for data recording with VR teleoperation, were copied according to these instructions: https://xlerobot.readthedocs.io/en/latest/software/getting_started/VLA_ACT.html#record-dataset-for-xlerobot-with-vr 

After that, dependencies were resolved, and they are saved no in the lerobot folder.

## Before starting: Update XLEVR_PATH 

The XLEVR_PATH needs to be updated in several Python files in both directories.

It needs to the the absolute path to the `XLeRobot/XLeVR` directory.

Search for "**XLEVR_PATH =**" in all Python files, and replace the current path with the path on your computer.

## Conda Environment

1. Create a new conda environment.

```
conda create -n xlerobot python=3.11
conda activate xlerobot
```

2. Install lerobot

In the terminal, first, navigate to the lerobot directory.

Then, install it from source:

```
pip install -e .
```

3. Install additional lerobot features:

```
pip install 'lerobot[feetech]'
```

4. Install additional libraries

```
pip install websockets
pip install scipy
```

If more are needed, install them as well.

5. If needed, install ffmpeg

If you see errors related to ffmpeg, try installing it with:

```
conda install ffmpeg=7.1.1 -c conda-forge
```

## Find ports for the two robotic arms.

Execute `lerobot-find-port` to find the ports of the two hands, following the instructions on the terminal.

In the recording script, these ports need to be passed as:
* 

## Calibration

When you execute the teleoperation command, you will be asked to do calibration first.

### Manual calibration

It is advised to do manual calibratoin, to be sure that all motors are correctly configured.

You will be asked in the terminal to calibrate the arms one by one. 
When calibrating the left arm, you need to also move the motors of thehead, that will hold the camera.

### Copying the calibration file directly
One way is to use the calibration file that was saved before, and copy it to your cache folder (`~/.cache/huggingface/lerobot/calibration/robots/xlerobot` or other, depending to your OS).

You can find the saved teleoperation file in this project, in `v1/calibration`.

## Camera Setup

After connecting the cameras to your computer, execute `lerobot-find-cameras opencv`.

You will see list with cameras, and the images taken from each camera will be saved to outputs/images in the current directory. 

Check which camera id corresponds to each of the robot cameras, and save it, as it will be used in the data recording command.

## Recording Command

In the terminal, navigate to the `lerobot` folder.

Execute the following command:

```
python src/lerobot/record.py \
  --robot.type=xlerobot \
  --robot.port1=/dev/tty.usbmodem5B3E0905011 \
  --robot.port2=/dev/tty.usbmodem5B610356121 \
  --robot.id=xlerobot_pi \
  --robot.cameras="{ head: {type: opencv, index_or_path: '0', width: 640, height: 480, fps: 10}, right: {type: opencv, index_or_path: '1', width: 640, height: 480, fps: 10}, left: {type: opencv, index_or_path: '0', width: 640, height: 480, fps: 10} }" \
  --dataset.repo_id=user/test_teleop \
  --dataset.single_task="Test teleop." \
  --dataset.root=user/test_teleop \
  --display_data=true \
  --teleop.type=xlerobot_vr 

```

Where:
* --robot.port1 - the port of the left arm
* --robot.port2 - the port of the right arm
* --robot.id - this id must correspond to the calibration file saved in your cache folder. If you did the calibration manually, the file will be saved with this name.
* --robot.cameras - Make sure to enter the correct camera IDs which you identified with the `lerobot-find-cameras` command.
* --robot.repo_id - user.repo_name where the data will be saved.
* --robot.root - The data will be saved in this directory, which is relative to the current directory.

## Teleoperation

Turn on the Meta Quest, open the browser and enter the URL that was given in the terminal.

When you open it, you should be able to control the robot arms and base with the Quest controllers.
