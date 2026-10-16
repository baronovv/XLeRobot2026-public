#!/bin/bash
# XLeRobot SLAM stack in tmux. Usage:
#   ./slam_up.sh            -> mapping mode (fresh ~/.ros/rtabmap.db if you deleted it)
#   ./slam_up.sh localize <db_path>  -> localization mode against saved map
MODE=${1:-map}
DB=${2:-$HOME/Documents/map_room_20260815_v2.db}
S="conda deactivate 2>/dev/null; source /opt/ros/jazzy/setup.bash"
CS="$S && source \$HOME/ros2_ws/install/setup.bash"

RT_COMMON="-r rgb/image:=/camera/color/image_raw -r depth/image:=/camera/depth/image_raw -r rgb/camera_info:=/camera/color/camera_info -p frame_id:=base_link -p odom_frame_id:=odom -p subscribe_depth:=true -p approx_sync:=true -p approx_sync_max_interval:=0.02 -p wait_for_transform:=0.3"
if [ "$MODE" = "localize" ]; then
  RT_ARGS="$RT_COMMON -p database_path:=$DB -p Mem/IncrementalMemory:=\"'false'\" -p Mem/InitWMWithAllNodes:=\"'true'\" -p Vis/MinInliers:=\"'12'\""
else
  RT_ARGS="$RT_COMMON"
fi

tmux kill-session -t slam 2>/dev/null
tmux new-session -d -s slam -n wheel
tmux send-keys -t slam:wheel "$S && python3 ~/xlerobot_slam/lekiwi_base_node.py --ros-args -p enable_drive:=true" C-m

tmux new-window -t slam -n camera
tmux send-keys -t slam:camera "$CS && ros2 launch orbbec_camera gemini_330_series.launch.py depth_registration:=true color_width:=640 color_height:=480 color_fps:=30 depth_width:=640 depth_height:=480 depth_fps:=30" C-m

tmux new-window -t slam -n tf
tmux send-keys -t slam:tf "$S && ros2 run tf2_ros static_transform_publisher --x 0.15 --y 0 --z 1.175 --frame-id base_link --child-frame-id camera_link" C-m

tmux new-window -t slam -n vo
tmux send-keys -t slam:vo "$S && sleep 10 && ros2 run rtabmap_odom rgbd_odometry --ros-args -r rgb/image:=/camera/color/image_raw -r depth/image:=/camera/depth/image_raw -r rgb/camera_info:=/camera/color/camera_info -p frame_id:=base_link -p odom_frame_id:=odom -p guess_frame_id:=odom_wheel -p approx_sync:=true -p approx_sync_max_interval:=0.02 -p wait_for_transform:=0.3" C-m

tmux new-window -t slam -n rtabmap
tmux send-keys -t slam:rtabmap "$S && sleep 14 && ros2 run rtabmap_slam rtabmap --ros-args $RT_ARGS" C-m

tmux new-window -t slam -n teleop
tmux send-keys -t slam:teleop "$S && sleep 16 && ros2 run teleop_twist_keyboard teleop_twist_keyboard" C-m

tmux new-window -t slam -n viz
tmux send-keys -t slam:viz "$S && export DISPLAY=:0 && sleep 16 && ros2 run rtabmap_viz rtabmap_viz --ros-args -r rgb/image:=/camera/color/image_raw -r depth/image:=/camera/depth/image_raw -r rgb/camera_info:=/camera/color/camera_info -p frame_id:=base_link -p odom_frame_id:=odom -p subscribe_depth:=true -p approx_sync:=true" C-m

echo "Stack starting in tmux session 'slam' ($MODE mode)."
echo "  tmux attach -t slam     | Ctrl-b n / Ctrl-b p = next/prev window | Ctrl-b d = detach"
echo "  Drive from the 'teleop' window (press z ~5x first to slow down)."
echo "  SHUTDOWN: go to 'rtabmap' window, single Ctrl-C, WAIT for 'Saving...done!', then: tmux kill-session -t slam"
