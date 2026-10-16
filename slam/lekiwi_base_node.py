#!/usr/bin/env python3
"""LeKiwi base node: wheel odometry from STS3215 position deltas + optional /cmd_vel drive.
Kinematics identical to lerobot xlerobot._wheel_raw_to_body / _body_to_wheel_raw."""
import math
import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from tf2_ros import TransformBroadcaster
from scservo_sdk import PortHandler, PacketHandler, COMM_SUCCESS

PORT = "/dev/serial/by-path/platform-3610000.usb-usb-0:2.4.1:1.0"
BAUD = 1_000_000
IDS = [7, 8, 9]  # left, back, right
ADDR_MODE, ADDR_TORQUE, ADDR_ACC, ADDR_GOAL_SPEED, ADDR_PRESENT_POS = 33, 40, 41, 46, 56
TICKS = 4096.0
WHEEL_R, BASE_R = 0.0425, 0.1215  # effective; geometric 0.14, slip-calibrated 2026-08-09
ANGLES = np.radians(np.array([240.0, 0.0, 120.0]) - 90.0)
M = np.array([[np.cos(a), np.sin(a), BASE_R] for a in ANGLES])
M_INV = np.linalg.inv(M)

def enc_speed(steps_ps: float) -> int:
    v = min(int(round(abs(steps_ps))), 32766)
    return (v | 0x8000) if steps_ps < 0 else v

class LekiwiBase(Node):
    def __init__(self):
        super().__init__("lekiwi_base")
        self.declare_parameter("enable_drive", False)
        self.declare_parameter("odom_frame", "odom_wheel")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("publish_tf", True)
        self.drive = self.get_parameter("enable_drive").value
        self.oframe = self.get_parameter("odom_frame").value
        self.bframe = self.get_parameter("base_frame").value
        self.pub_tf = self.get_parameter("publish_tf").value

        self.port = PortHandler(PORT)
        self.pkt = PacketHandler(0)
        if not self.port.openPort() or not self.port.setBaudRate(BAUD):
            raise RuntimeError(f"cannot open {PORT}")
        for mid in IDS:
            _, res, _ = self.pkt.ping(self.port, mid)
            if res != COMM_SUCCESS:
                raise RuntimeError(f"wheel ID {mid} not responding (12V off?)")
        if self.drive:
            for mid in IDS:
                self.pkt.write1ByteTxRx(self.port, mid, ADDR_MODE, 1)   # speed mode
                self.pkt.write1ByteTxRx(self.port, mid, ADDR_ACC, 20)
                self.pkt.write1ByteTxRx(self.port, mid, ADDR_TORQUE, 1)
            self.get_logger().info("drive ENABLED")
        else:
            for mid in IDS:
                self.pkt.write1ByteTxRx(self.port, mid, ADDR_TORQUE, 0)
            self.get_logger().info("drive disabled: wheels freewheel, odometry only")

        self.x = self.y = self.th = 0.0
        self.total_yaw = 0.0
        self.prev = None
        self.prev_t = None
        self.cmd = (0.0, 0.0, 0.0)
        self.cmd_t = 0.0
        self.odom_pub = self.create_publisher(Odometry, "wheel_odom", 10)
        self.br = TransformBroadcaster(self)
        self.create_subscription(Twist, "cmd_vel", self.on_cmd, 10)
        self.timer = self.create_timer(0.05, self.loop)  # 20 Hz

    def on_cmd(self, msg: Twist):
        self.cmd = (msg.linear.x, msg.linear.y, msg.angular.z)
        self.cmd_t = self.get_clock().now().nanoseconds * 1e-9

    def read_pos(self):
        out = []
        try:
            for mid in IDS:
                pos, res, _ = self.pkt.read2ByteTxRx(self.port, mid, ADDR_PRESENT_POS)
                if res != COMM_SUCCESS:
                    return None
                out.append(pos)
        except Exception as e:
            self.get_logger().warn(f"serial hiccup: {e}", throttle_duration_sec=2.0)
            try:
                self.port.ser.reset_input_buffer()
            except Exception:
                pass
            self.prev = None  # drop this interval so a stale delta never integrates
            self.drops = getattr(self, 'drops', 0) + 1
            self.get_logger().warn(f'dropped intervals so far: {self.drops}')
            return None
        return out

    def loop(self):
        now = self.get_clock().now()
        t = now.nanoseconds * 1e-9
        pos = self.read_pos()
        if pos is None:
            return
        if self.prev is not None:
            dt = t - self.prev_t
            if dt <= 0:
                return
            deltas = [((p - q + TICKS / 2) % TICKS) - TICKS / 2 for p, q in zip(pos, self.prev)]
            wheel_radps = np.array(deltas) / TICKS * 2.0 * math.pi / dt
            body = M_INV.dot(wheel_radps * WHEEL_R)  # [vx, vy, wz]
            vx, vy, wz = body
            mid_th = self.th + wz * dt * 0.5
            self.x += (vx * math.cos(mid_th) - vy * math.sin(mid_th)) * dt
            self.y += (vx * math.sin(mid_th) + vy * math.cos(mid_th)) * dt
            self.th = (self.th + wz * dt + math.pi) % (2 * math.pi) - math.pi
            self.total_yaw += wz * dt
            self.get_logger().info(f'total yaw: {math.degrees(self.total_yaw):+.1f} deg', throttle_duration_sec=1.0)
            self.publish(now, vx, vy, wz)
        self.prev, self.prev_t = pos, t

        if self.drive:
            fresh = (t - self.cmd_t) < 0.5
            vx, vy, wz = self.cmd if fresh else (0.0, 0.0, 0.0)
            wheel_lin = M.dot(np.array([vx, vy, wz]))
            steps_ps = wheel_lin / WHEEL_R / (2.0 * math.pi) * TICKS
            for mid, s in zip(IDS, steps_ps):
                self.pkt.write2ByteTxRx(self.port, mid, ADDR_GOAL_SPEED, enc_speed(s))

    def publish(self, now, vx, vy, wz):
        qz, qw = math.sin(self.th / 2.0), math.cos(self.th / 2.0)
        od = Odometry()
        od.header.stamp = now.to_msg()
        od.header.frame_id = self.oframe
        od.child_frame_id = self.bframe
        od.pose.pose.position.x = self.x
        od.pose.pose.position.y = self.y
        od.pose.pose.orientation.z = qz
        od.pose.pose.orientation.w = qw
        od.pose.covariance[0] = od.pose.covariance[7] = 1e-3
        od.pose.covariance[35] = 1e-2
        od.twist.twist.linear.x = vx
        od.twist.twist.linear.y = vy
        od.twist.twist.angular.z = wz
        od.twist.covariance[0] = od.twist.covariance[7] = 1e-3
        od.twist.covariance[35] = 1e-2
        self.odom_pub.publish(od)
        if self.pub_tf:
            tf = TransformStamped()
            tf.header.stamp = od.header.stamp
            tf.header.frame_id = self.oframe
            tf.child_frame_id = self.bframe
            tf.transform.translation.x = self.x
            tf.transform.translation.y = self.y
            tf.transform.rotation.z = qz
            tf.transform.rotation.w = qw
            self.br.sendTransform(tf)

    def shutdown(self):
        try:
            for mid in IDS:
                self.pkt.write2ByteTxRx(self.port, mid, ADDR_GOAL_SPEED, 0)
                self.pkt.write1ByteTxRx(self.port, mid, ADDR_TORQUE, 0)
            self.port.closePort()
        except Exception:
            pass

def main():
    rclpy.init()
    node = LekiwiBase()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == "__main__":
    main()
