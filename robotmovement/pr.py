import pathlib, shutil, sys
D = pathlib.Path(".").resolve()
def edit(name, pairs):
    p = D / name; src = p.read_text(encoding="utf-8")
    if "EXITCODE_PATCH" in src: print(f"  {name}: already patched"); return
    for old, new in pairs:
        if src.count(old) != 1: sys.exit(f"ABORT: anchor missing in {name}\n{old!r}")
        src = src.replace(old, new)
    shutil.copy2(p, str(p) + ".bak"); p.write_text(src, encoding="utf-8")
    print(f"  {name}: patched (.bak saved)")

edit("robot_core.py", [
 ("def execute_route(mission_fn):\n",
  "def execute_route(mission_fn):  # EXITCODE_PATCH: returns True only on success\n"),
 ('        print("[!] Нет валидных данных с датчиков F/B. Проверьте ESP32 и порт.")\n        tele.stop()\n        return\n',
  '        print("[!] Нет валидных данных с датчиков F/B. Проверьте ESP32 и порт.")\n        tele.stop()\n        return False\n'),
 ('        print(f"[!] Ошибка подключения к роботу: {e}")\n        tele.stop()\n        return\n',
  '        print(f"[!] Ошибка подключения к роботу: {e}")\n        tele.stop()\n        return False\n'),
 ("    # --- 4. Миссия ---\n    try:\n        mission_fn(base, tele)\n    except KeyboardInterrupt:\n",
  "    # --- 4. Миссия ---\n    ok = False\n    try:\n        mission_fn(base, tele)\n        ok = True\n    except KeyboardInterrupt:\n"),
 ('        tele.stop()\n        print("Завершено. Порты освобождены.")',
  '        tele.stop()\n        print("Завершено. Порты освобождены.")\n\n    return ok\n'),
])
for n in (1, 2, 3):
    edit(f"route_part{n}.py", [
     (f'if __name__ == "__main__":\n    execute_route(mission_part{n})',
      f'# EXITCODE_PATCH\nif __name__ == "__main__":\n    import sys\n    sys.exit(0 if execute_route(mission_part{n}) else 1)\n')])
print("done")
