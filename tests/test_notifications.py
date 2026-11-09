from datetime import datetime
import logging
import threading

import pytest

from mqtt_schedule.notifications import SmsNotifications, SmsSendError, SmsSubmission


STARTED_AT = datetime(2026, 11, 9, 12, 0)
RECIPIENTS = ("+15550002222", "+15550003333")


class FakeSender:
    def __init__(self, *, expected_calls=1, error=None):
        self.calls = []
        self.expected_calls = expected_calls
        self.error = error
        self.done = threading.Event()

    def send(self, *, to_number, body):
        self.calls.append((to_number, body, threading.get_ident()))
        if len(self.calls) >= self.expected_calls:
            self.done.set()
        if self.error is not None and len(self.calls) == 1:
            raise self.error
        return SmsSubmission("SM" + "1" * 32, "queued")


@pytest.mark.parametrize("startup_enabled", [False, True])
def test_global_switch_blocks_all_sms_events(startup_enabled: bool) -> None:
    sender = FakeSender()
    notifications = SmsNotifications(
        enabled=False, service_start_enabled=startup_enabled, sender=sender, recipients=RECIPIENTS,
    )
    try:
        assert not notifications.notify_service_started(host_name="server", source_serial="123", started_at=STARTED_AT)
        assert not notifications.notify(event="future_alert", body="Test")
        assert sender.calls == []
    finally:
        notifications.close()


def test_startup_event_switch_blocks_startup_only() -> None:
    sender = FakeSender()
    notifications = SmsNotifications(enabled=True, service_start_enabled=False, sender=sender, recipients=RECIPIENTS[:1])
    try:
        assert not notifications.notify_service_started(host_name="server", source_serial="123", started_at=STARTED_AT)
        assert sender.calls == []
        assert notifications.notify(event="future_alert", body="Test")
        assert sender.done.wait(1)
    finally:
        notifications.close()


def test_startup_notifies_once_per_unique_recipient_in_worker(caplog) -> None:
    caplog.set_level(logging.INFO)
    sender = FakeSender(expected_calls=2)
    notifications = SmsNotifications(
        enabled=True, service_start_enabled=True, sender=sender, recipients=RECIPIENTS + RECIPIENTS[:1],
    )
    try:
        assert notifications.notify_service_started(host_name="linux-server", source_serial="123", started_at=STARTED_AT)
        assert not notifications.notify_service_started(host_name="linux-server", source_serial="123", started_at=STARTED_AT)
        assert sender.done.wait(1)
    finally:
        notifications.close()
    assert [call[0] for call in sender.calls] == list(RECIPIENTS)
    assert all("linux-server" in call[1] and "server 123" in call[1] and "2026-11-09T12:00:00" in call[1] for call in sender.calls)
    assert all(call[2] != threading.get_ident() for call in sender.calls)
    assert "sms_notification_submitted" in caplog.text
    assert all(number not in caplog.text for number in RECIPIENTS)


@pytest.mark.parametrize("error", [SmsSendError("twilio_http_error", http_status=401, provider_code=20003),
                                       RuntimeError("test-only-secret +15550002222")])
def test_sender_failure_is_isolated_and_next_recipient_is_attempted(error, caplog) -> None:
    caplog.set_level(logging.INFO)
    sender = FakeSender(expected_calls=2, error=error)
    notifications = SmsNotifications(enabled=True, service_start_enabled=True, sender=sender, recipients=RECIPIENTS)
    try:
        assert notifications.notify_service_started(host_name="server", source_serial="123", started_at=STARTED_AT)
        assert sender.done.wait(1)
    finally:
        notifications.close()
    assert len(sender.calls) == 2
    assert "sms_notification_failed" in caplog.text
    assert "sms_notification_submitted" in caplog.text
    assert "test-only-secret" not in caplog.text
    assert all(number not in caplog.text for number in RECIPIENTS)


def test_slow_sender_does_not_block_enqueue_and_close_prevents_new_sends() -> None:
    entered = threading.Event()
    release = threading.Event()

    class SlowSender:
        def send(self, **kwargs):
            entered.set()
            assert release.wait(2)
            return SmsSubmission("SM" + "1" * 32, "queued")

    notifications = SmsNotifications(enabled=True, service_start_enabled=True, sender=SlowSender(), recipients=RECIPIENTS[:1])
    try:
        assert notifications.notify_service_started(host_name="server", source_serial="123", started_at=STARTED_AT)
        assert entered.wait(1)
        assert notifications.notify(event="future_alert", body="Queued without waiting for HTTP")
    finally:
        release.set()
        notifications.close()
    assert not notifications.notify(event="future_alert", body="Closed")
