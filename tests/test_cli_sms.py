from dataclasses import replace
from types import SimpleNamespace
import logging
import sys

import pytest

from mqtt_schedule import cli
from mqtt_schedule.settings import RuntimeSettings


@pytest.fixture
def settings(tmp_path):
    return RuntimeSettings(
        schedule_file=tmp_path / "schedule.json",
        controller_file=tmp_path / "controller.json",
        access_users_file=tmp_path / "users.json",
        clients_sysinfo_dir=tmp_path / "sysinfo",
        openweather_current_file=tmp_path / "current.json",
        openweather_forecast_file=tmp_path / "forecast.json",
        tempest_data_dir=tmp_path / "tempest",
        device_serial_file=tmp_path / "serial.txt",
        controller_status_file=tmp_path / "status.json",
        source_serial_override="123",
        sms_enabled=True,
        twilio_account_sid="AC" + "0" * 32,
        twilio_auth_token="test-only-private-token",
        twilio_from_number="+15550001111",
        twilio_to_numbers=("+15550002222",),
    )


@pytest.mark.parametrize("disabled,dry_run", [(True, False), (False, True)])
def test_disabled_or_dry_run_does_not_create_twilio_sender(settings, monkeypatch, disabled, dry_run):
    def forbidden(*args, **kwargs):
        pytest.fail("Disabled SMS must not initialize the transport")

    monkeypatch.setattr(cli, "TwilioSmsSender", forbidden)
    notifier = cli.build_sms_notifications(replace(settings, sms_enabled=not disabled), dry_run=dry_run)
    try:
        assert notifier.enabled is False
        assert not notifier.notify(event="service_start", body="Test")
    finally:
        notifier.close()


@pytest.mark.parametrize("overrides,reason", [
    ({"twilio_auth_token": None}, "missing_configuration"),
    ({"twilio_to_numbers": ()}, "missing_configuration"),
    ({"twilio_from_number": "bad-number"}, "invalid_configuration"),
    ({"twilio_to_numbers": ("bad-number",)}, "invalid_configuration"),
    ({"twilio_account_sid": "bad-account"}, "invalid_configuration"),
])
def test_bad_sms_configuration_is_disabled_without_exposing_values(settings, overrides, reason, caplog):
    caplog.set_level(logging.INFO)
    notifier = cli.build_sms_notifications(replace(settings, **overrides))
    try:
        assert notifier.enabled is False
        assert reason in caplog.text
        assert settings.twilio_auth_token not in caplog.text
        assert settings.twilio_from_number not in caplog.text
        assert "bad-number" not in caplog.text
        assert "bad-account" not in caplog.text
    finally:
        notifier.close()


def test_valid_sms_configuration_deduplicates_recipients(settings):
    notifier = cli.build_sms_notifications(replace(settings, twilio_to_numbers=("+15550002222", " +15550002222 ")))
    try:
        assert notifier.enabled is True
        assert notifier.recipients == ("+15550002222",)
    finally:
        notifier.close()


def prepare_cli(monkeypatch, settings, *, fail_service=False):
    events = []
    monkeypatch.setattr(cli.RuntimeSettings, "from_env", staticmethod(lambda: settings))
    monkeypatch.setattr(cli, "_ensure_required_airtable_files", lambda _: None)
    monkeypatch.setattr(cli.HostInfoProvider, "get_identity", lambda _: SimpleNamespace(
        session_client_id="test-session", host_name="test-linux", ip_address="127.0.0.1",
    ))
    monkeypatch.setattr(cli.LegacyCsvRecorder, "from_settings", lambda _: object())
    monkeypatch.setattr(cli.PahoClientFactory, "connect", lambda *a, **k: object())
    monkeypatch.setattr(cli.PahoClientFactory, "close", lambda _: events.append("mqtt_closed"))
    for name in (
        "build_weather_refresh_jobs", "build_airtable_sync_jobs", "build_openweather_mongo_ingest_jobs",
        "build_tempest_mongo_ingest_jobs", "build_mqtt_request_jobs", "build_controller_status_jobs",
    ):
        monkeypatch.setattr(cli, name, lambda **kwargs: [])

    class FakeApplication:
        def __init__(self, **kwargs):
            pass

        def run_schedule_tick(self, now):
            return SimpleNamespace(evaluated_at=now, command_count=0)

    class FakeRunner:
        def __init__(self, *args, **kwargs):
            pass

        def run_forever(self):
            events.append("service_loop")
            if fail_service:
                raise RuntimeError("test service error")
            return 0

    class FakeNotifier:
        def __init__(self, channel):
            self.channel = channel

        def notify_service_started(self, **kwargs):
            events.append((f"{self.channel}_start", kwargs))

        def close(self):
            events.append(f"{self.channel}_closed")

    def build_notifications(value, *, dry_run=False):
        events.append(("sms_build", dry_run))
        return FakeNotifier("sms")

    def build_email_notifications(value, *, dry_run=False):
        events.append(("email_build", dry_run))
        return FakeNotifier("email")

    monkeypatch.setattr(cli, "SchedulerApplication", FakeApplication)
    monkeypatch.setattr(cli, "ServiceRunner", FakeRunner)
    monkeypatch.setattr(cli.SignalAwareService, "install_signal_handlers", lambda _: None)
    monkeypatch.setattr(cli, "build_sms_notifications", build_notifications)
    monkeypatch.setattr(cli, "build_email_notifications", build_email_notifications)
    return events


@pytest.mark.parametrize("dry_run", [False, True])
def test_service_mode_wires_startup_event_and_closes_worker(settings, monkeypatch, dry_run):
    events = prepare_cli(monkeypatch, settings)
    monkeypatch.setattr(sys, "argv", ["mqtt_schedule", "--service"] + (["--dry-run"] if dry_run else []))
    assert cli.main() == 0
    assert ("sms_build", dry_run) in events
    startup = [item for item in events if isinstance(item, tuple) and item[0] == "sms_start"]
    assert len(startup) == 1
    assert startup[0][1]["host_name"] == "test-linux"
    assert startup[0][1]["source_serial"] == "123"
    assert events.index(startup[0]) < events.index("service_loop")
    assert "sms_closed" in events


def test_service_exception_closes_sms_worker(settings, monkeypatch):
    events = prepare_cli(monkeypatch, settings, fail_service=True)
    monkeypatch.setattr(sys, "argv", ["mqtt_schedule", "--service"])
    with pytest.raises(RuntimeError, match="test service error"):
        cli.main()
    assert events[-2:] == ["sms_closed", "mqtt_closed"]
    assert "email_closed" in events


@pytest.mark.parametrize("dry_run", [False, True])
def test_one_shot_commands_do_not_start_sms(settings, monkeypatch, dry_run):
    events = prepare_cli(monkeypatch, settings)
    monkeypatch.setattr(sys, "argv", ["mqtt_schedule"] + (["--dry-run"] if dry_run else []))
    assert cli.main() == 0
    assert not any(isinstance(item, tuple) and item[0].startswith(("sms_", "email_")) for item in events)


@pytest.mark.parametrize("dry_run", [False, True])
def test_service_mode_wires_email_startup_with_sms_and_closes_both(settings, monkeypatch, dry_run):
    events = prepare_cli(monkeypatch, replace(settings, email_enabled=True))
    monkeypatch.setattr(sys, "argv", ["mqtt_schedule", "--service"] + (["--dry-run"] if dry_run else []))
    assert cli.main() == 0
    assert ("email_build", dry_run) in events
    email_startups = [item for item in events if isinstance(item, tuple) and item[0] == "email_start"]
    sms_startups = [item for item in events if isinstance(item, tuple) and item[0] == "sms_start"]
    assert len(email_startups) == len(sms_startups) == 1
    assert email_startups[0][1] == sms_startups[0][1]
    assert events.index(email_startups[0]) < events.index("service_loop")
    expected_cleanup = ["email_closed", "sms_closed"] + ([] if dry_run else ["mqtt_closed"])
    assert events[-len(expected_cleanup):] == expected_cleanup
