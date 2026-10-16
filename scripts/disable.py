from lerobot.robots.so100_follower import SO100Follower, SO100FollowerConfig

config = SO100FollowerConfig(port="/dev/ttyACM1", id="my_follower_arm")
robot = SO100Follower(config)
robot.connect(calibrate=False)
robot.bus.disable_torque()
input("Torque отключён. Нажмите Enter для выхода...")