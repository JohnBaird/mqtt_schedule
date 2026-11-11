from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime
import gzip
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import re
import tempfile
import threading
from time import time
from typing import Callable, Iterator, TextIO
from urllib.parse import quote, quote_plus
from zoneinfo import ZoneInfo

from .logging_setup import log_paths
from .notifications import EmailAttachment, EmailNotifications, EmailReportPart
from .settings import RuntimeSettings


LOG_HEADER = re.compile(
    r"^\S+\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+\S+\s+created=(\d+(?:\.\d+)?)\s"
)
PART_CHARACTERS = 256 * 1024


class ReportRedactor:
    def __init__(self, settings: RuntimeSettings) -> None:
        values = [getattr(settings, name) for name in (
            "mqtt_password", "email_password", "twilio_auth_token", "airtable_api_key",
            "openweather_api_key", "tempest_token", "mongo_password",
        )]
        self.secrets = sorted({encoded for value in values if isinstance(value, str) and value
                               for encoded in (value, quote(value, safe=""), quote_plus(value))}, key=len, reverse=True)
        self.fields = re.compile(
            r'''(?ix)(["']?(?:password|auth_token|api_key|apikey|access_token|token|appid|pinCode|pinNumber|cardNumber|faceId|matched_credential)["']?\s*[:=]\s*)("[^"\r\n]*"|'[^'\r\n]*'|[^\s&,;}]+)'''
        )

    def redact(self, value: str) -> str:
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(\w+://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", value)
        return self.fields.sub(lambda match: match.group(1) + "[REDACTED]", value)


@dataclass
class CollectedIssues:
    counts: dict[str, int]
    first: float | None = None
    last: float | None = None
    characters: int = 0
    files: int = 0
    read_errors: int = 0
    unrecognized_lines: int = 0


class LogReportSource:
    def __init__(self, settings: RuntimeSettings, *, host_name: str,
                 handler: TimedRotatingFileHandler | None = None) -> None:
        self.settings = settings
        self.host_name = host_name
        self.handler = handler
        self.timezone = ZoneInfo(settings.timezone_name)
        self.redactor = ReportRedactor(settings)

    def _collect(self, output: TextIO, *, start: float | None, end: float) -> CollectedIssues:
        result = CollectedIssues({"CRITICAL": 0, "ERROR": 0, "WARNING": 0})
        with ExitStack() as stack:
            streams = []
            if self.handler is not None:
                self.handler.acquire()
            try:
                if self.handler is not None:
                    self.handler.flush()
                for path in log_paths(self.settings.log_file):
                    try:
                        stream = stack.enter_context(path.open("rb"))
                        streams.append((stream, os.fstat(stream.fileno()).st_size))
                    except OSError:
                        result.read_errors += 1
            finally:
                if self.handler is not None:
                    self.handler.release()
            # Capture byte limits under the handler lock, then release it before scanning.
            # Linux open descriptors remain readable if normal rotation renames the files.
            for stream, remaining in streams:
                result.files += 1
                selected = False
                seen_header = False
                try:
                    while remaining > 0:
                        raw = stream.readline(remaining)
                        if not raw:
                            result.read_errors += 1
                            break
                        remaining -= len(raw)
                        line = raw.decode("utf-8", errors="replace")
                        match = LOG_HEADER.match(line)
                        if match:
                            seen_header = True
                            stamp = float(match.group(2))
                            selected = (stamp < end and (start is None or stamp >= start)
                                        and match.group(1) in result.counts)
                            if stamp < end:
                                result.first = stamp if result.first is None else min(result.first, stamp)
                                result.last = stamp if result.last is None else max(result.last, stamp)
                            if selected:
                                result.counts[match.group(1)] += 1
                        elif not seen_header and line.strip():
                            result.unrecognized_lines += 1
                        if selected:
                            safe = self.redactor.redact(line)
                            output.write(safe)
                            result.characters += len(safe)
                except OSError:
                    result.read_errors += 1
        return result

    def parts(self, *, end: datetime, all_history: bool = False) -> Iterator[EmailReportPart]:
        if end.tzinfo is None:
            raise ValueError("Report end must include a timezone")
        end_epoch = end.timestamp()
        start = None if all_history else end_epoch - 86400
        kind = "startup" if all_history else "daily"
        local_end = end.astimezone(self.timezone)
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", newline="\n") as details:
            collected = self._collect(details, start=start, end=end_epoch)
            number_of_parts = max(1, (collected.characters + PART_CHARACTERS - 1) // PART_CHARACTERS)
            window = ("All retained application history" if start is None else
                      f"{datetime.fromtimestamp(start, self.timezone).isoformat()} to {local_end.isoformat()}")
            lines = [f"MQTT Schedule {kind} log report", f"Host: {self.host_name}",
                     f"Period: {window}", f"Cutoff: {local_end.isoformat()} (exclusive)",
                     "Scope: application logfiles; native systemd lifecycle messages remain in the journal.",
                     "", *(f"{level}: {count}" for level, count in collected.counts.items())]
            if not sum(collected.counts.values()):
                lines.append("No WARNING, ERROR or CRITICAL entries found in the available application logs.")
            if collected.first is not None:
                lines.append(f"Earliest available record: {datetime.fromtimestamp(collected.first, self.timezone).isoformat()}")
                lines.append(f"Latest available record: {datetime.fromtimestamp(collected.last, self.timezone).isoformat()}")
            if collected.first is None or (start is not None and collected.first > start):
                lines.append("INCOMPLETE HISTORY: available records do not establish coverage of the whole requested period.")
            if collected.read_errors or collected.unrecognized_lines:
                lines.append(f"INCOMPLETE COLLECTION: read errors={collected.read_errors}; unrecognized leading lines={collected.unrecognized_lines}.")
            lines.extend([f"Logfiles read: {collected.files}",
                          "Details are redacted and attached in full; numbered parts may continue an earlier traceback.",
                          "Report generation does not clear logs. No automatic email retries or delivery confirmation."])
            details.seek(0)
            for number in range(1, number_of_parts + 1):
                text = details.read(PART_CHARACTERS)
                attachments = ()
                if text:
                    filename = f"mqtt_schedule_{kind}_{local_end.strftime('%Y%m%dT%H%M%S')}_part{number:03d}.txt.gz"
                    attachments = (EmailAttachment(filename, gzip.compress(text.encode("utf-8"), mtime=0)),)
                yield EmailReportPart(
                    f"MQTT Schedule {kind} log report - {local_end.date()} [{number}/{number_of_parts}]",
                    self.redactor.redact("\n".join(lines) + f"\nPart {number} of {number_of_parts}.\n"), attachments,
                )


class DailyLogReportScheduler:
    """Calendar check only; preparation and SMTP run in the existing email worker."""

    def __init__(self, settings: RuntimeSettings, notifications: EmailNotifications, source: LogReportSource,
                 *, clock: Callable[[], float] = time) -> None:
        self.settings = settings
        self.notifications = notifications
        self.source = source
        self.clock = clock
        self.timezone = ZoneInfo(settings.timezone_name)
        self._startup_checked = False
        self._attempted_date: str | None = None
        self._lock = threading.Lock()
        self.logger = logging.getLogger("mqtt_schedule.log_reports")

    def tick(self) -> None:
        if not self.settings.daily_log_report_enabled or not self.settings.email_enabled or not self.notifications.enabled:
            return
        with self._lock:
            now = datetime.fromtimestamp(self.clock(), self.timezone)
            if not self._startup_checked:
                self._startup_checked = True
                if self.settings.daily_log_report_run_immediately:
                    accepted = self.notifications.notify_report(
                        event="log_report_startup", factory=lambda end=now: self.source.parts(end=end, all_history=True),
                    )
                    self.logger.log(logging.INFO if accepted else logging.ERROR,
                                    "startup_log_report_requested queued=%s", accepted)
            hour, minute = map(int, self.settings.daily_log_report_time.split(":"))
            due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            day = due.date().isoformat()
            if now < due or self._attempted_date == day:
                return
            self._attempted_date = day
            try:
                last_date = self._last_attempt()
                if last_date is not None and last_date > day:
                    self.logger.warning("daily_log_report_skipped reason=future_state date=%s last_attempted_date=%s", day, last_date)
                    return
                if last_date is not None and last_date >= day:
                    return
                self._claim(day)
            except (OSError, ValueError):
                self.logger.error("daily_log_report_skipped reason=state_unavailable date=%s", day)
                return
            accepted = self.notifications.notify_report(
                event="log_report_daily", factory=lambda end=due: self.source.parts(end=end),
            )
            self.logger.log(logging.INFO if accepted else logging.ERROR,
                            "daily_log_report_requested date=%s scheduled_at=%s queued=%s", day, due.isoformat(), accepted)

    def _last_attempt(self) -> str | None:
        try:
            if self.settings.daily_log_report_state_file.stat().st_size > 4096:
                raise ValueError("Oversized report state")
            payload = json.loads(self.settings.daily_log_report_state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload.get("version") != 1:
            raise ValueError("Invalid report state")
        last = payload.get("last_attempted_date")
        if not isinstance(last, str) or date.fromisoformat(last).isoformat() != last:
            raise ValueError("Invalid report state date")
        return last

    def _claim(self, day: str) -> None:
        path = self.settings.daily_log_report_state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "last_attempted_date": day}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
