# Updates
Let's put here all updates, together with accounts and passwords.

## RustDesk 
Done by Pavlo on 15.07.2026.

In order to easier access monitor of our Jetson Orin Nano we downloaded RustDesk.

- Version: 1.4.9
- ID: 53 659 211
- Password: JetsonXX

## Admin Panel 
Done by Tsvetomila on 14.07.2026.

We have an admin panel for managing dishes, residents and serving jobs.


## Setting up Teleoperation with Meta Quest
Done by Tsvetomila on 27.06.2026.

Teleoperation was setup to work on the robot, using these instructions: https://xlerobot.readthedocs.io/en/latest/software/getting_started/VLA_ACT.html#record-dataset-for-xlerobot-with-vr

The problem was that the XLeRobot was probably using lerobot 0.4.1, but the latest version of LeRobot is 0.5.1. Therefore, the older LeRobot version needed to be cloned.

In addition to the version, still some additional changes needed to be made to solve dependency issues, in order to make the setup working.

The updated code that works is now in folder `v1`. The guide of how to setup is given in `v1/README_v1.md`.

## Setting up Meta Quest
Done by Tsvetomila on 26.06.2026.

To use the Meta Quest, we needed to have:
* email address
* setup on the Meta Horizon app



## Flashing Jetson Orin Nano to v7.2
Done by Tsvetomila on 25.06.2026.

Updated the Jetson to JetPack 7.2 following this guide: https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/quick_start.html

* Username: jetsonX

* Password: jetsonX

* Computer name: jetsonX

Issues: there was a problem with the monitor or HDMI-to-DisplayPort cable – the Jetson was not visible on the monitor. Other than that, all went fine.
