from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
import os
from pathlib import Path

from .settings import RuntimeSettings


FILE_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s created=%(created).6f %(message)s"
FILE_LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
HANDLER_NAME = "mqtt_schedule_daily_file"


def configure_file_logging(settings: RuntimeSettings) -> TimedRotatingFileHandler:
    """Use unmodified stdlib daily rotation; preserve the existing console handler."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.name == HANDLER_NAME:
            root.removeHandler(handler)
            handler.close()
    settings.log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    # Precreate privately; the standard handler then appends without truncating history.
    fd = os.open(settings.log_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
    os.close(fd)
    handler = TimedRotatingFileHandler(
        settings.log_file, when="midnight", interval=1,
        backupCount=settings.log_backup_count, encoding="utf-8", utc=False,
    )
    handler.set_name(HANDLER_NAME)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(FILE_LOG_FORMAT, datefmt=FILE_LOG_DATE_FORMAT))
    root.addHandler(handler)
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    logging.getLogger("mqtt_schedule.logging").info(
        "file_logging_configured file=%s rotation=midnight backup_count=%s timezone=server_local",
        settings.log_file, settings.log_backup_count,
    )
    return handler


def close_file_logging(handler: TimedRotatingFileHandler | None) -> None:
    if handler is not None:
        logging.getLogger().removeHandler(handler)
        handler.close()


def log_paths(log_file: Path) -> list[Path]:
    """Only native daily archives and the active file; exclude unrelated files."""
    from datetime import date

    paths = []
    for candidate in log_file.parent.glob(log_file.name + ".*"):
        suffix = candidate.name[len(log_file.name) + 1:]
        try:
            date.fromisoformat(suffix)
        except ValueError:
            continue
        if len(suffix) == 10:
            paths.append(candidate)
    paths.sort()
    if log_file.exists():
        paths.append(log_file)
    return paths
