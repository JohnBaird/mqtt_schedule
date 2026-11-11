from dataclasses import replace
from datetime import datetime, timedelta, timezone
import gzip
import io
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import sys
import runpy
import threading
from time import time

import pytest

from mqtt_schedule import cli
from mqtt_schedule.log_history import import_journal_history
from mqtt_schedule.log_reports import DailyLogReportScheduler, LogReportSource
from mqtt_schedule.logging_setup import (
    FILE_LOG_DATE_FORMAT, FILE_LOG_FORMAT, close_file_logging, configure_file_logging,
)
from mqtt_schedule.notifications import EmailNotifications, EmailReportPart, EmailSubmission
from mqtt_schedule.service import ServiceRunner
from mqtt_schedule.settings import RuntimeSettings


END = datetime.fromisoformat("2026-11-11T21:00:00-05:00")


@pytest.fixture
def settings(tmp_path):
    return RuntimeSettings(
        schedule_file=tmp_path / "schedule.json", controller_file=tmp_path / "controllers.json",
        access_users_file=tmp_path / "users.json", clients_sysinfo_dir=tmp_path / "sysinfo",
        openweather_current_file=tmp_path / "weather.json", openweather_forecast_file=tmp_path / "forecast.json",
        tempest_data_dir=tmp_path / "tempest", device_serial_file=tmp_path / "serial.txt",
        log_file=tmp_path / "logs" / "mqtt_schedule.log", daily_log_report_state_file=tmp_path / "report-state.json",
        daily_log_report_enabled=True, email_enabled=True, email_password="private-test-password",
        airtable_api_key="private-test-api-key",
    )


def log_line(stamp, level="WARNING", message="test_issue", continuation=""):
    record = logging.LogRecord("mqtt_schedule.test", getattr(logging, level), "", 0, message, (), None)
    record.created = stamp.timestamp()
    return logging.Formatter(FILE_LOG_FORMAT, datefmt=FILE_LOG_DATE_FORMAT).format(record) + "\n" + continuation


def write_log(settings, text, suffix=""):
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    path = settings.log_file.with_name(settings.log_file.name + suffix)
    path.write_text(text, encoding="utf-8")
    return path


def details(parts):
    return "".join(gzip.decompress(attachment.content).decode("utf-8")
                   for part in parts for attachment in part.attachments)


def test_file_logging_uses_exact_standard_midnight_handler_and_not_size_rotation(settings):
    root = logging.getLogger()
    old_level = root.level
    handler = configure_file_logging(settings)
    try:
        assert type(handler) is TimedRotatingFileHandler
        assert handler.when == "MIDNIGHT" and handler.interval == 86400
        assert handler.backupCount == 7 and handler.utc is False
        assert not hasattr(handler, "maxBytes")
        handler.rolloverAt = int(time()) + 86400
        logging.getLogger("mqtt_schedule.test").warning("x" * 100000)
        logging.getLogger("mqtt_schedule.test").error("still_same_day")
        assert not list(settings.log_file.parent.glob("mqtt_schedule.log.*"))
        assert settings.log_file.stat().st_size > 100000
        handler.rolloverAt = int(time()) - 1
        logging.getLogger("mqtt_schedule.test").warning("after_rollover")
        archives = list(settings.log_file.parent.glob("mqtt_schedule.log.*"))
        assert len(archives) == 1 and "still_same_day" in archives[0].read_text()
        assert "after_rollover" in settings.log_file.read_text()
    finally:
        close_file_logging(handler)
        root.setLevel(old_level)


def test_daily_report_filters_exact_window_and_preserves_whole_traceback(settings):
    start = END - timedelta(hours=24)
    write_log(settings, log_line(start - timedelta(seconds=1), message="old_issue") +
              log_line(start, message="at_start") +
              log_line(start + timedelta(hours=1), "ERROR", "failed", "Traceback (most recent call last):\n  source line\nValueError: failure\n"),
              ".2026-11-10")
    write_log(settings, log_line(END - timedelta(minutes=1), "CRITICAL", "critical_issue") +
              log_line(END - timedelta(seconds=10), "INFO", "routine_activity") +
              log_line(END, message="at_cutoff"))
    parts = list(LogReportSource(settings, host_name="test-host").parts(end=END))
    assert len(parts) == 1
    assert "WARNING: 1" in parts[0].body and "ERROR: 1" in parts[0].body and "CRITICAL: 1" in parts[0].body
    text = details(parts)
    assert "at_start" in text and "ValueError: failure" in text and "source line" in text
    assert "old_issue" not in text and "routine_activity" not in text and "at_cutoff" not in text
    assert "INCOMPLETE HISTORY" not in parts[0].body


def test_startup_report_reads_all_retained_issues_not_just_24_hours(settings):
    write_log(settings, log_line(END - timedelta(days=5), message="old_retained_issue"), ".2026-11-06")
    write_log(settings, log_line(END - timedelta(minutes=1), message="new_issue"))
    source = LogReportSource(settings, host_name="test")
    daily = list(source.parts(end=END))
    startup = list(source.parts(end=END, all_history=True))
    assert "WARNING: 1" in daily[0].body and "old_retained_issue" not in details(daily)
    assert "WARNING: 2" in startup[0].body and "old_retained_issue" in details(startup)


def test_report_uses_actual_24_hours_across_dst_change(settings):
    end = datetime.fromisoformat("2026-11-01T21:00:00-05:00")
    write_log(settings,
              log_line(datetime.fromisoformat("2026-10-31T21:30:00-04:00"), message="outside_actual_24h") +
              log_line(datetime.fromisoformat("2026-10-31T22:00:00-04:00"), message="inside_actual_24h"))
    parts = list(LogReportSource(settings, host_name="test").parts(end=end))
    assert "WARNING: 1" in parts[0].body
    assert "outside_actual_24h" not in details(parts) and "inside_actual_24h" in details(parts)


def test_report_redacts_configured_secrets_url_credentials_and_access_credentials(settings):
    write_log(settings, log_line(END - timedelta(minutes=1), "ERROR",
              'failed private-test-password https://example.test/?api_key=private-test-api-key&token=abc123 '
              'mongodb://user:secret@host/db pinNumber="12345" matched_credential=54321'))
    parts = list(LogReportSource(settings, host_name="test").parts(end=END))
    text = details(parts) + parts[0].body
    for secret in ("private-test-password", "private-test-api-key", "abc123", "user:secret", "12345", "54321"):
        assert secret not in text
    assert "[REDACTED]" in text


def test_large_reports_are_numbered_and_never_silently_truncated(settings, monkeypatch):
    import mqtt_schedule.log_reports as module
    monkeypatch.setattr(module, "PART_CHARACTERS", 80)
    original = log_line(END - timedelta(seconds=1), message="x" * 1000)
    write_log(settings, original)
    parts = list(LogReportSource(settings, host_name="test").parts(end=END))
    assert len(parts) > 2 and details(parts).replace("\r\n", "\n") == original
    assert f"[{len(parts)}/{len(parts)}]" in parts[-1].subject
    assert all("WARNING: 1" in part.body for part in parts)


def test_empty_or_short_history_is_not_claimed_as_a_complete_healthy_period(settings):
    parts = list(LogReportSource(settings, host_name="test").parts(end=END))
    assert "No WARNING" in parts[0].body and "INCOMPLETE HISTORY" in parts[0].body
    assert parts[0].attachments == ()
    write_log(settings, log_line(END - timedelta(hours=1), "INFO", "first_start"))
    assert "INCOMPLETE HISTORY" in list(LogReportSource(settings, host_name="test").parts(end=END))[0].body


def test_unreadable_log_is_reported_as_incomplete(settings, monkeypatch):
    path = write_log(settings, log_line(END - timedelta(minutes=1)))
    original = Path.open
    def fail(self, *args, **kwargs):
        if self == path:
            raise PermissionError("sensitive details")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail)
    parts = list(LogReportSource(settings, host_name="test").parts(end=END))
    assert "INCOMPLETE COLLECTION: read errors=1" in parts[0].body
    assert "sensitive details" not in parts[0].body


class Notifications:
    enabled = True
    def __init__(self, accepted=True):
        self.calls = []
        self.accepted = accepted
    def notify_report(self, **kwargs):
        self.calls.append(kwargs)
        return self.accepted


class Source:
    def __init__(self):
        self.calls = []
    def parts(self, **kwargs):
        self.calls.append(kwargs)
        yield EmailReportPart("Test", "Test")


def scheduler(settings, *, at=END, notifications=None, source=None):
    clock = [at.timestamp()]
    notifications = notifications if notifications is not None else Notifications()
    source = source if source is not None else Source()
    value = DailyLogReportScheduler(settings, notifications, source, clock=lambda: clock[0])
    return value, clock, notifications, source


def test_daily_schedule_fires_at_21_and_deduplicates_restarts(settings):
    value, clock, notifications, source = scheduler(settings, at=END - timedelta(seconds=1))
    value.tick()
    assert not notifications.calls
    clock[0] += 1
    value.tick()
    value.tick()
    restarted, _, _, _ = scheduler(settings, notifications=notifications, at=END + timedelta(minutes=1))
    restarted.tick()
    assert len(notifications.calls) == 1
    list(notifications.calls[0]["factory"]())
    assert source.calls == [{"end": END}]
    clock[0] = (END + timedelta(days=1)).timestamp()
    value.tick()
    assert len(notifications.calls) == 2


def test_startup_diagnostic_is_independent_and_covers_all_history(settings):
    settings = replace(settings, daily_log_report_run_immediately=True)
    value, _, notifications, source = scheduler(settings, at=END - timedelta(hours=4))
    value.tick()
    value.tick()
    assert len(notifications.calls) == 1 and notifications.calls[0]["event"] == "log_report_startup"
    list(notifications.calls[0]["factory"]())
    assert source.calls[0]["all_history"] is True
    restarted, _, _, _ = scheduler(settings, notifications=notifications, at=END - timedelta(hours=3))
    restarted.tick()
    assert len(notifications.calls) == 2


@pytest.mark.parametrize("changes", [{"daily_log_report_enabled": False}, {"email_enabled": False}])
def test_master_switches_disable_startup_and_daily_reports(settings, changes):
    value, _, notifications, _ = scheduler(replace(settings, daily_log_report_run_immediately=True, **changes))
    value.tick()
    assert not notifications.calls and not settings.daily_log_report_state_file.exists()


def test_disabled_transport_never_queues_reports(settings):
    notifications = Notifications()
    notifications.enabled = False
    value, _, _, _ = scheduler(settings, notifications=notifications)
    value.tick()
    assert not notifications.calls


def test_daily_same_day_catchup_does_not_replay_older_days(settings):
    value, _, notifications, source = scheduler(settings, at=END + timedelta(hours=1))
    value.tick()
    list(notifications.calls[0]["factory"]())
    assert source.calls == [{"end": END}]
    assert len(notifications.calls) == 1


def test_corrupt_report_state_is_preserved_and_error_is_not_spammed(settings, caplog):
    settings.daily_log_report_state_file.write_text("not json", encoding="utf-8")
    value, _, notifications, _ = scheduler(settings)
    value.tick()
    value.tick()
    assert not notifications.calls
    assert settings.daily_log_report_state_file.read_text() == "not json"
    assert sum("reason=state_unavailable" in item.message for item in caplog.records) == 1


def test_queue_rejection_is_logged_and_daily_attempt_is_not_automatically_retried(settings, caplog):
    value, _, notifications, _ = scheduler(settings, notifications=Notifications(accepted=False))
    value.tick()
    value.tick()
    assert len(notifications.calls) == 1 and "queued=False" in caplog.text
    assert settings.daily_log_report_state_file.exists()


def test_calendar_checks_do_not_add_start_complete_messages_every_poll(caplog):
    calls = []
    runner = ServiceRunner(object(), scheduled_checks=[lambda: calls.append(1)])
    runner._run_scheduled_checks()
    runner._run_scheduled_checks()
    assert calls == [1, 1]
    assert not caplog.records


def journal_row(stamp, message, pid="123", priority="6"):
    return json.dumps({"__REALTIME_TIMESTAMP": str(int(stamp.timestamp() * 1000000)),
                       "MESSAGE": message, "_PID": pid, "PRIORITY": priority}) + "\n"


def test_history_import_preserves_text_severity_even_if_journal_priority_is_info_and_keeps_traceback(settings):
    now = datetime.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    before = now - timedelta(days=1)
    source = journal_row(before, "2026-11-10 12:00:00,000 ERROR mqtt_schedule.service failed", priority="6")
    source += journal_row(before, "Traceback: test detail")
    source += journal_row(now, "Native service warning", pid="1", priority="4")
    result = import_journal_history(settings, io.StringIO(source), now=now)
    assert result == {"records": 2, "continuation_lines": 1, "skipped_outside_retention": 0, "files": 2}
    parts = list(LogReportSource(settings, host_name="test").parts(end=now + timedelta(seconds=1), all_history=True))
    assert "ERROR: 1" in parts[0].body and "WARNING: 1" in parts[0].body
    assert "Traceback: test detail" in details(parts)
    assert "Native service warning" in details(parts)
    with pytest.raises(ValueError, match="already exist"):
        import_journal_history(settings, io.StringIO(source), now=now)


def test_import_skips_history_older_than_retention_and_never_overwrites_existing_files(settings):
    now = datetime.now().astimezone()
    source = journal_row(now - timedelta(days=8), "too old") + journal_row(now, "retained")
    result = import_journal_history(settings, io.StringIO(source), now=now)
    assert result["skipped_outside_retention"] == 1
    original = settings.log_file.read_bytes()
    with pytest.raises(ValueError):
        import_journal_history(settings, io.StringIO(source), now=now)
    assert settings.log_file.read_bytes() == original


def test_report_generation_runs_in_existing_email_worker_not_caller_thread(settings):
    done = threading.Event()
    calls = []
    class Sender:
        def send(self, **kwargs):
            calls.append((kwargs, threading.get_ident()))
            done.set()
            return EmailSubmission("test-id")
    notifier = EmailNotifications(enabled=True, service_start_enabled=False, sender=Sender(), recipients=("one@example.test",))
    write_log(settings, log_line(END - timedelta(minutes=1)))
    try:
        assert notifier.notify_report(event="log_report_daily", factory=lambda: LogReportSource(settings, host_name="test").parts(end=END))
        assert done.wait(2)
        assert calls[0][1] != threading.get_ident()
        assert calls[0][0]["attachments"]
    finally:
        notifier.close()


def test_preview_cli_never_opens_transports_or_changes_report_state(settings, monkeypatch, capsys):
    write_log(settings, log_line(END - timedelta(minutes=1)))
    monkeypatch.setattr(cli.RuntimeSettings, "from_env", staticmethod(lambda: settings))
    def forbidden(*args, **kwargs):
        pytest.fail("Preview must not initialize service resources")
    monkeypatch.setattr(cli, "_ensure_required_airtable_files", forbidden)
    monkeypatch.setattr(cli, "build_email_notifications", forbidden)
    monkeypatch.setattr(cli.PahoClientFactory, "connect", forbidden)
    monkeypatch.setattr(sys, "argv", ["mqtt_schedule", "--preview-log-report", "--now", END.isoformat()])
    assert cli.main() == 0
    assert "WARNING: 1" in capsys.readouterr().out
    assert not settings.daily_log_report_state_file.exists()


def test_report_worker_survives_factory_failure_and_sends_next_notification(caplog):
    done = threading.Event()
    class Sender:
        def send(self, **kwargs):
            done.set()
            return EmailSubmission("test-next")
    notifier = EmailNotifications(enabled=True, service_start_enabled=False, sender=Sender(), recipients=("one@example.test",))
    def fail():
        raise RuntimeError("secret-test-password")
    try:
        assert notifier.notify_report(event="log_report_daily", factory=fail)
        assert notifier.notify(event="input_edge", subject="Test", body="Test")
        assert done.wait(2)
    finally:
        notifier.close()
    assert "email_log_report_failed" in caplog.text and "secret-test-password" not in caplog.text


def test_report_state_write_failure_prevents_email(settings, monkeypatch, caplog):
    value, _, notifications, _ = scheduler(settings)
    def fail(day):
        raise PermissionError("private filesystem details")
    monkeypatch.setattr(value, "_claim", fail)
    value.tick()
    assert not notifications.calls and "reason=state_unavailable" in caplog.text
    assert "private filesystem details" not in caplog.text


def test_import_cli_never_initializes_mqtt_email_or_file_handler(settings, monkeypatch, capsys):
    now = datetime.now().astimezone()
    monkeypatch.setattr(cli.RuntimeSettings, "from_env", staticmethod(lambda: settings))
    monkeypatch.setattr(sys, "stdin", io.StringIO(journal_row(now, "Native warning", priority="4")))
    def forbidden(*args, **kwargs):
        pytest.fail("History import must not initialize service resources")
    monkeypatch.setattr(cli, "_ensure_required_airtable_files", forbidden)
    monkeypatch.setattr(cli, "configure_file_logging", forbidden)
    monkeypatch.setattr(cli, "build_email_notifications", forbidden)
    monkeypatch.setattr(cli.PahoClientFactory, "connect", forbidden)
    monkeypatch.setattr(sys, "argv", ["mqtt_schedule", "--import-log-history"])
    assert cli.main() == 0
    assert "log_history_import records=1" in capsys.readouterr().out
    assert not settings.daily_log_report_state_file.exists()


@pytest.mark.parametrize("bad", ["not json", "[]", '{"MESSAGE": "test"}',
                               '{"MESSAGE": [], "__REALTIME_TIMESTAMP": "1"}'])
def test_invalid_history_import_never_overwrites_logs(settings, bad):
    with pytest.raises(ValueError):
        import_journal_history(settings, io.StringIO(bad))
    assert not settings.log_file.exists()


def test_report_timezone_is_not_the_host_timezone(settings):
    settings = replace(settings, timezone_name="America/Los_Angeles")
    at = datetime.fromisoformat("2026-11-11T21:00:00-05:00")  # 18:00 in the configured zone.
    value, clock, notifications, _ = scheduler(settings, at=at)
    value.tick()
    assert not notifications.calls
    clock[0] += 3 * 3600
    value.tick()
    assert len(notifications.calls) == 1


def test_standard_retention_selects_only_excess_dated_archives(settings):
    root = logging.getLogger()
    old_level = root.level
    handler = configure_file_logging(settings)
    try:
        for day in range(1, 10):
            write_log(settings, "test archive", f".2020-01-{day:02d}")
        selected = handler.getFilesToDelete()
        assert len(selected) == 2
        assert all(name.endswith(("2020-01-01", "2020-01-02")) for name in selected)
        assert len(list(settings.log_file.parent.glob("mqtt_schedule.log.*"))) == 9
    finally:
        close_file_logging(handler)
        root.setLevel(old_level)


def test_future_daily_state_is_visible_and_does_not_send_a_duplicate(settings, caplog):
    settings.daily_log_report_state_file.write_text(json.dumps({
        "version": 1, "last_attempted_date": "2026-12-01",
    }), encoding="utf-8")
    value, _, notifications, _ = scheduler(settings)
    value.tick()
    assert not notifications.calls and "reason=future_state" in caplog.text


def test_module_entrypoint_records_unhandled_failures_as_critical(monkeypatch, caplog):
    def fail():
        raise RuntimeError("test fatal failure")
    monkeypatch.setattr(cli, "main", fail)
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("mqtt_schedule", run_name="__main__")
    assert caught.value.code == 1
    assert any(item.levelno == logging.CRITICAL and item.message == "application_failed" and item.exc_info
               for item in caplog.records)


def test_report_parts_attempt_each_recipient_and_keep_working_after_a_failure(caplog):
    from mqtt_schedule.notifications import EmailSendError
    calls = []
    done = threading.Event()
    class Sender:
        def send(self, **kwargs):
            calls.append((kwargs["to_address"], kwargs["subject"]))
            if len(calls) == 1:
                raise EmailSendError("test_smtp_failure")
            if len(calls) == 4:
                done.set()
            return EmailSubmission("test-id")
    def parts():
        yield EmailReportPart("Part 1", "Test")
        yield EmailReportPart("Part 2", "Test")
    notifier = EmailNotifications(enabled=True, service_start_enabled=False, sender=Sender(),
                                  recipients=("one@example.test", "two@example.test"))
    try:
        assert notifier.notify_report(event="log_report_daily", factory=parts)
        assert done.wait(2)
    finally:
        notifier.close()
    assert calls == [("one@example.test", "Part 1"), ("two@example.test", "Part 1"),
                     ("one@example.test", "Part 2"), ("two@example.test", "Part 2")]
    assert "email_notification_failed" in caplog.text
