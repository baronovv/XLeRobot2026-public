import subprocess
import sys


def main():
    # Список команд в строгом порядке выполнения
    commands = [
        "python3 route_part1.py",

        """lerobot-rollout --strategy.type=episodic --robot.type=so101_follower --robot.port=/dev/ttyACM1 --robot.id=my_follower_arm_left --robot.cameras="{ top: {type: opencv, index_or_path: /dev/video0, width: 640, height: 480, fps: 15}, wrist: {type: opencv, index_or_path: /dev/video8, width: 640, height: 480, fps: 15} }" --display_data=false --dataset.repo_id=ktotomama/rollout_left_arm_kulho --dataset.root=/home/jetson8/lerobot_eval_left_kulho --dataset.single_task="Pick up the object and put it in the kulho" --dataset.num_episodes=5 --dataset.push_to_hub=false --policy.path=/home/jetson8/trained_policies/act_right_arm_maissi/checkpoints/030000/pretrained_model --dataset.fps=30""",

        "python3 route_part2.py",

        """lerobot-rollout --strategy.type=episodic --robot.type=so101_follower --robot.port=/dev/ttyACM1 --robot.id=my_follower_arm_left --robot.cameras="{ top: {type: opencv, index_or_path: /dev/video0, width: 640, height: 480, fps: 15}, wrist: {type: opencv, index_or_path: /dev/video8, width: 640, height: 480, fps: 15} }" --display_data=false --dataset.repo_id=ktotomama/rollout_left_arm_kulho --dataset.root=/home/jetson8/lerobot_eval_left_kulho --dataset.single_task="Pick up the object and put it in the kulho" --dataset.num_episodes=5 --dataset.push_to_hub=false --policy.path=/home/jetson8/trained_policies/act_right_arm_kulho/checkpoints/030000/pretrained_model --dataset.fps=15""",

        "python3 route_part3.py"
    ]

    print("Начинаем выполнение цепочки команд...\n" + "-" * 50)

    for i, cmd in enumerate(commands, start=1):
        # Выводим только начало длинной команды, чтобы не засорять терминал
        short_cmd_name = cmd.split()[0] if not cmd.startswith('lerobot') else 'lerobot-rollout'
        print(f"\n[Шаг {i}/{len(commands)}] Запуск: {short_cmd_name} ...")

        try:
            # shell=True позволяет передавать команду целиком как строку, включая кавычки и скобки
            # check=True вызовет исключение, если команда завершится с ошибкой (код возврата != 0)
            subprocess.run(cmd, shell=True, check=True)
            print(f"[Шаг {i}/{len(commands)}] Успешно завершен.")
        except subprocess.CalledProcessError as e:
            print(f"\n[ОШИБКА] Шаг {i} прерван с кодом: {e.returncode}")
            print("Остановка выполнения следующих шагов.")
            sys.exit(e.returncode)
        except KeyboardInterrupt:
            print("\n[ОТМЕНА] Выполнение прервано пользователем.")
            sys.exit(1)

    print("\n" + "-" * 50 + "\nВсе шаги успешно выполнены! Программа завершается.")


if __name__ == "__main__":
    main()