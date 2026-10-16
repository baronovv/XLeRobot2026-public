"""
event_logger.py — centralized logging for the meal service app.

All other modules (navigation, policies, main) call log_event() rather
than configuring their own loggers, so every event ends up in one place
with a consistent format. This is the primary debugging tool while
navigation/policy execution are still stubbed.

Each run of the app creates its own timestamped log file under
config.LOG_DIR, so separate executions never overwrite each other's logs.
"""

import os
import logging
from datetime import datetime

import config


def setup_logging() -> logging.Logger:
    """
    Configures the app-wide logger: writes to both stdout and a log file
    under config.LOG_DIR, named with the start time of this run
    (e.g. logs/meal_service_2026-07-14_13-42-05.log).

    Call this once at app startup (in main.py) before any other module
    logs anything.
    """
    logger = logging.getLogger("meal_service")
    logger.setLevel(logging.INFO)

    # avoid adding duplicate handlers if setup_logging() is ever called twice
    if logger.handlers:
        return logger

    # make sure the logs directory exists before writing into it
    os.makedirs(config.LOG_DIR, exist_ok=True)

    # one file per execution, named with this run's start timestamp
    run_timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = os.path.join(config.LOG_DIR, f"meal_service_{run_timestamp}.log")

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info(f"logging to {log_path}")
    return logger


# module-level logger instance, shared by every file that imports this module
logger = logging.getLogger("meal_service")


def log_event(event: str, **details) -> None:
    """
    Logs one structured event line, e.g.:
        log_event("navigate_start", location_id="seat_1")
        -> "navigate_start | location_id=seat_1"

    Using a single function for all event logging (rather than scattered
    logger.info() calls with ad-hoc messages) keeps the log format
    consistent and easy to grep/parse later.
    """
    if details:
        detail_str = " ".join(f"{k}={v}" for k, v in details.items())
        logger.info(f"{event} | {detail_str}")
    else:
        logger.info(event)
