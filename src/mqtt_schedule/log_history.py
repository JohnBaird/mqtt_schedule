from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timedelta
import json
import logging
import os
import re
from typing import TextIO

from .logging_setup import FILE_LOG_DATE_FORMAT, FILE_LOG_FORMAT, log_paths
from .settings import RuntimeSettings


_APP_HEADER = re.compile(
    r"^\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[,.:+\d-]*)\s+"
    r"(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+(\S+)\s+(.*)$"
)


def import_journal_history(settings: RuntimeSettings, source: TextIO, *, now: datetime | None = None) -> dict[str, int]:
    """Explicit one-time journal-JSON import into an empty daily-log destination."""
    if settings.log_file.exists() or log_paths(settings.log_file):
        raise ValueError("Logfiles already exist; history import must run before the first file-logging start")
    today = (now or datetime.now().astimezone()).date()
    oldest = today - timedelta(days=settings.log_backup_count)
    formatter = logging.Formatter(FILE_LOG_FORMAT, datefmt=FILE_LOG_DATE_FORMAT)
    settings.log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    counts = {"records": 0, "continuation_lines": 0, "skipped_outside_retention": 0, "files": 0}
    writers = {}
    contexts = {}
    with ExitStack() as stack:
        for raw in source:
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict) or not isinstance(row.get("MESSAGE"), str):
                raise ValueError("Expected journal JSON records with text MESSAGE fields")
            stamp_raw = row.get("__REALTIME_TIMESTAMP")
            if not isinstance(stamp_raw, str) or not stamp_raw.isascii() or not stamp_raw.isdigit():
                raise ValueError("Expected journal microsecond timestamps")
            stamp = int(stamp_raw) / 1000000
            day = datetime.fromtimestamp(stamp).date()
            if not oldest <= day <= today:
                counts["skipped_outside_retention"] += 1
                continue
            message = row["MESSAGE"]
            pid = str(row.get("_PID", ""))
            match = _APP_HEADER.match(message)
            if match is None and pid and pid in contexts:
                contexts[pid].write(message + "\n")
                counts["continuation_lines"] += 1
                continue
            path = settings.log_file if day == today else settings.log_file.with_name(settings.log_file.name + "." + day.isoformat())
            if path not in writers:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
                writers[path] = stack.enter_context(os.fdopen(fd, "w", encoding="utf-8", newline="\n"))
                counts["files"] += 1
            stream = writers[path]
            if match:
                level = getattr(logging, match.group(1))
                logger_name, message = match.group(2), match.group(3)
                if pid:
                    contexts[pid] = stream
            else:
                priority = str(row.get("PRIORITY", "6"))
                level = {"0": logging.CRITICAL, "1": logging.CRITICAL, "2": logging.CRITICAL,
                         "3": logging.ERROR, "4": logging.WARNING, "7": logging.DEBUG}.get(priority, logging.INFO)
                logger_name = "mqtt_schedule.journal_history"
            record = logging.LogRecord(logger_name, level, "", 0, message, (), None)
            record.created = stamp
            record.msecs = (stamp % 1) * 1000
            stream.write(formatter.format(record) + "\n")
            counts["records"] += 1
    if not counts["records"]:
        raise ValueError("No journal records in the configured retention period were imported")
    return counts
