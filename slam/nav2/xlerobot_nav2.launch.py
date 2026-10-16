#!/usr/bin/env python3
"""Minimal Nav2 bringup for XLeRobot: no docking, no route server.
Map + map->odom come from rtabmap (already running separately)."""
import os
from launch import LaunchDescription
from launch_ros.actions import Node

PARAMS = os.path.expanduser('~/xlerobot_slam/nav2/nav2_params.yaml')

NODES = [
    ('nav2_controller',       'controller_server',  'controller_server'),
    ('nav2_smoother',         'smoother_server',    'smoother_server'),
    ('nav2_planner',          'planner_server',     'planner_server'),
    ('nav2_behaviors',        'behavior_server',    'behavior_server'),
    ('nav2_bt_navigator',     'bt_navigator',       'bt_navigator'),
    ('nav2_waypoint_follower','waypoint_follower',  'waypoint_follower'),
    ('nav2_velocity_smoother','velocity_smoother',  'velocity_smoother'),
    ('nav2_collision_monitor','collision_monitor',  'collision_monitor'),
]

def generate_launch_description():
    actions = []
    for pkg, exe, name in NODES:
        remaps = [('/tf', 'tf'), ('/tf_static', 'tf_static')]
        if name in ('controller_server', 'behavior_server', 'waypoint_follower',
                    'velocity_smoother'):
            remaps.append(('cmd_vel', 'cmd_vel_nav'))
        actions.append(Node(
            package=pkg, executable=exe, name=name,
            output='screen', parameters=[PARAMS],
            remappings=remaps,
        ))
    actions.append(Node(
        package='nav2_lifecycle_manager', executable='lifecycle_manager',
        name='lifecycle_manager_navigation', output='screen',
        parameters=[{
            'autostart': True,
            'node_names': [n for _, _, n in NODES],
            'bond_timeout': 10.0,
        }],
    ))
    return LaunchDescription(actions)
