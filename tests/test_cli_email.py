from dataclasses import replace
import logging

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
        email_enabled=True,
        sender_email_address="sender@example.test",
        email_password="test-only-private-password",
        receiver_email_addresses=("recipient@example.test",),
    )


@pytest.mark.parametrize("disabled,dry_run", [(True, False), (False, True)])
def test_disabled_or_dry_run_never_creates_email_transport(settings, monkeypatch, disabled, dry_run):
    def forbidden(*args, **kwargs):
        pytest.fail("Email transport must not initialize when disabled or dry-running")

    monkeypatch.setattr(cli, "SmtpEmailSender", forbidden)
    notifier = cli.build_email_notifications(replace(settings, email_enabled=not disabled), dry_run=dry_run)
    try:
        assert notifier.enabled is False
        assert not notifier.notify(event="test", subject="Test", body="Test")
    finally:
        notifier.close()


@pytest.mark.parametrize("overrides,reason", [
    ({"email_password": None}, "missing_configuration"),
    ({"sender_email_address": " "}, "missing_configuration"),
    ({"receiver_email_addresses": ()}, "missing_configuration"),
    ({"sender_email_address": "bad-email"}, "invalid_configuration"),
    ({"sender_email_address": "name@"}, "invalid_configuration"),
    ({"receiver_email_addresses": ("bad-recipient",)}, "invalid_configuration"),
    ({"receiver_email_addresses": ("@example.test",)}, "invalid_configuration"),
    ({"email_smtp_port": 0}, "invalid_configuration"),
    ({"email_smtp_timeout_seconds": 0}, "invalid_configuration"),
    ({"email_smtp_host": None}, "invalid_configuration"),
])
def test_email_misconfiguration_disables_only_email_without_logging_secrets(settings, overrides, reason, caplog):
    caplog.set_level(logging.INFO)
    notifier = cli.build_email_notifications(replace(settings, **overrides))
    try:
        assert notifier.enabled is False
        assert reason in caplog.text
        assert settings.email_password not in caplog.text
        assert settings.sender_email_address not in caplog.text
        assert settings.receiver_email_addresses[0] not in caplog.text
        assert "bad-email" not in caplog.text
        assert "bad-recipient" not in caplog.text
    finally:
        notifier.close()


def test_valid_email_configuration_deduplicates_recipients_without_opening_smtp(settings, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("SMTP connections must only open in the sending worker")

    monkeypatch.setattr("mqtt_schedule.email_adapter.smtplib.SMTP", forbidden)
    notifier = cli.build_email_notifications(replace(settings, receiver_email_addresses=(
        "recipient@example.test", " recipient@example.test ",
    )))
    try:
        assert notifier.enabled is True
        assert notifier.recipients == ("recipient@example.test",)
    finally:
        notifier.close()
