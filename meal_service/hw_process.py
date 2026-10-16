"""
hw_process.py — runs one hardware-owning child process (a route script or a
lerobot-rollout) to completion, and keeps consecutive ones apart.

Route scripts and policy rollouts open the same Feetech motor buses and
cameras, one process after another. Opening a bus the previous process has
only just closed hangs (seen on the Jetson with back-to-back route legs), so
every hardware process first waits until config.HARDWARE_SETTLE_SECONDS have
passed since the previous one exited: route -> route, route -> policy,
policy -> route and policy -> policy alike. Keeping that rule in one place is
the whole reason navigation.py and policies.py share this module.

Stopping a child is done with exactly ONE SIGINT, then a grace period for
it to stop its wheels / return the arm to rest and release the bus, then
SIGKILL only if it's still running. Children run in their own session, so a
Ctrl-C in the terminal reaches only this app, which forwards that one
SIGINT. Previously the terminal's SIGINT and a forwarded one both arrived:
lerobot treats a second SIGINT as "force exit, skip teardown", and in a
route script it raises a second KeyboardInterrupt inside the wheel-stop
cleanup. A second Ctrl-C here means "kill it now".
"""

import os
import signal
import subprocess
import threading
import time
from collections import deque

import config
from event_logger import log_event

INHERIT = "inherit"  # stdin mode: child shares this app's stdin

# time.monotonic() at which the last hardware process exited, None if none yet
_last_release = None


class Result:
    def __init__(self, returncode, timed_out, tail, seen):
        self.returncode = returncode
        self.timed_out = timed_out  # True if stopped by the timeout
        self.tail = tail            # last output lines, for error messages
        self.seen = seen            # which `watch` substrings appeared in the output


def wait_for_settle(label: str) -> None:
    """Sleeps until HARDWARE_SETTLE_SECONDS have passed since the last
    hardware process exited. No-op before the first one."""
    if _last_release is None:
        return
    remaining = config.HARDWARE_SETTLE_SECONDS - (time.monotonic() - _last_release)
    if remaining > 0:
        log_event("hardware_settle_wait", before=label, seconds=round(remaining, 1))
        time.sleep(remaining)


def _mark_released() -> None:
    global _last_release
    _last_release = time.monotonic()


def _interrupt(process: subprocess.Popen, grace_s: float, label: str) -> None:
    """One SIGINT, a grace period to shut down cleanly, then SIGKILL.
    A Ctrl-C during the grace period kills it immediately."""
    process.send_signal(signal.SIGINT)  # no-op if it already exited
    try:
        process.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        log_event("hardware_process_killed", label=label, pid=process.pid, reason="grace_expired")
        process.kill()
        process.wait()
    except KeyboardInterrupt:
        log_event("hardware_process_killed", label=label, pid=process.pid, reason="second_ctrl_c")
        process.kill()
        process.wait()
        raise


def run(command: list, label: str, timeout_s: float, grace_s: float,
        cwd: str = None, stdin=INHERIT, tail_lines: int = 15,
        log_path: str = None, watch=()) -> Result:
    """
    Runs `command` to completion, echoing its output live prefixed with
    [label]. Blocks for the whole run -- this is the robot's stop.

    stdin: INHERIT, None (-> /dev/null, so any unexpected input() prompt fails
           instead of hanging), or a string written to the child's stdin
           once, then closed.
    log_path: if set, the child's full output is also written there.
    watch: substrings to look for in the output (reported in Result.seen).

    Never raises for a failed or timed-out child -- the caller reads the
    Result and decides. Re-raises KeyboardInterrupt after the child has
    stopped.
    """
    wait_for_settle(label)

    if stdin == INHERIT:
        stdin_arg = None
    elif stdin is None:
        stdin_arg = subprocess.DEVNULL
    else:
        stdin_arg = subprocess.PIPE

    # PYTHONUNBUFFERED so progress arrives line by line while it runs
    env = dict(os.environ, PYTHONUNBUFFERED="1")

    tail = deque(maxlen=tail_lines)
    seen = set()
    # opened before the child starts, so a bad path can't orphan a moving robot
    log_file = open(log_path, "w", encoding="utf-8") if log_path else None

    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=stdin_arg,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
        start_new_session=True,  # terminal signals go to this app only
    )

    # Output is pumped on a thread so the main thread can own the timeout and
    # Ctrl-C handling: a hung child prints nothing, so waiting on its output
    # would wait forever.
    def _pump():
        for line in process.stdout:
            line = line.rstrip()
            print(f"[{label}] {line}", flush=True)
            tail.append(line)
            for pattern in watch:
                if pattern in line:
                    seen.add(pattern)
            if log_file:
                log_file.write(line + "\n")
                log_file.flush()

    reader = threading.Thread(target=_pump, daemon=True)
    reader.start()

    timed_out = False
    try:
        try:
            if stdin_arg is subprocess.PIPE:
                try:
                    process.stdin.write(stdin)
                    process.stdin.close()
                except OSError:
                    pass  # child already exited; its exit code will say why
            process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            log_event("hardware_process_timeout", label=label, timeout_seconds=round(timeout_s))
            _interrupt(process, grace_s, label)
    except KeyboardInterrupt:
        print(f"[{label}] Ctrl-C: stopping it cleanly (up to {round(grace_s)}s) "
              f"-- Ctrl-C again to kill it now", flush=True)
        _interrupt(process, grace_s, label)
        raise
    finally:
        reader.join(timeout=5)
        if not reader.is_alive():  # else a grandchild still holds the pipe; leave it
            process.stdout.close()
            if log_file:
                log_file.close()
        _mark_released()

    return Result(process.returncode, timed_out, list(tail), seen)
