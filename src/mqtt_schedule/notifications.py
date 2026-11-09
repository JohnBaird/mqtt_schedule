from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from queue import Empty, Full, Queue
import threading
from typing import Generic, Protocol, TypeVar
from uuid import uuid4


@dataclass(frozen=True)
class SmsSubmission:
    message_sid: str
    status: str


class SmsSendError(Exception):
    def __init__(self, reason: str, *, http_status: int | None = None, provider_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status
        self.provider_code = provider_code


class SmsSender(Protocol):
    def send(self, *, to_number: str, body: str) -> SmsSubmission:
        ...


@dataclass(frozen=True)
class EmailSubmission:
    message_id: str
    status: str = "accepted"


class EmailSendError(Exception):
    def __init__(self, reason: str, *, smtp_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.smtp_code = smtp_code


class EmailSender(Protocol):
    def send(self, *, to_address: str, subject: str, body: str) -> EmailSubmission:
        ...


@dataclass(frozen=True)
class _Notification:
    notification_id: str
    event: str
    body: str
    subject: str


_Sender = TypeVar("_Sender")


class _BackgroundNotifications(Generic[_Sender]):
    """Share bounded queuing and lifecycle while each channel owns its transport."""

    def __init__(
        self,
        *,
        enabled: bool,
        service_start_enabled: bool,
        channel: str,
        sender: _Sender | None = None,
        recipients: tuple[str, ...] = (),
    ) -> None:
        self.enabled = enabled
        self.service_start_enabled = service_start_enabled
        self.sender = sender
        self.recipients = tuple(dict.fromkeys(recipients))
        self._channel = channel
        self.logger = logging.getLogger("mqtt_schedule.notifications")
        self._queue: Queue[_Notification] = Queue(maxsize=20)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._startup_notified = False

    def notify_service_started(self, *, host_name: str, source_serial: str, started_at: datetime) -> bool:
        with self._lock:
            if self._startup_notified:
                return False
            self._startup_notified = True
        if not self.service_start_enabled:
            self.logger.info("%s_notification_skipped event=service_start reason=event_disabled", self._channel)
            return False
        return self._enqueue(
            event="service_start",
            subject=f"MQTT Schedule started on {host_name}",
            body=(
                f"MQTT Schedule started on {host_name} (server {source_serial}) "
                f"at {started_at.isoformat(timespec='seconds')}."
            ),
        )

    def _enqueue(self, *, event: str, body: str, subject: str = "") -> bool:
        with self._lock:
            if not self.enabled or self._closed:
                return False
            if self.sender is None or not self.recipients:
                self.logger.warning("%s_notification_skipped event=%s reason=not_configured", self._channel, event)
                return False
            notification = _Notification(uuid4().hex, event, body, subject)
            try:
                self._queue.put_nowait(notification)
            except Full:
                self.logger.warning("%s_notification_skipped event=%s reason=queue_full", self._channel, event)
                return False
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name=f"mqtt-schedule-{self._channel}", daemon=True)
                self._thread.start()
        self.logger.info(
            "%s_notification_queued event=%s notification_id=%s recipient_count=%s",
            self._channel,
            event,
            notification.notification_id,
            len(self.recipients),
        )
        return True

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._stop.set()
            worker = self._thread
        if worker is not None:
            worker.join(timeout=1.0)
            if worker.is_alive():
                self.logger.info("%s_worker_stopping reason=request_in_progress", self._channel)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                notification = self._queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                self._send(notification)
            finally:
                self._queue.task_done()

    def _send(self, notification: _Notification) -> None:
        assert self.sender is not None
        for index, recipient in enumerate(self.recipients, start=1):
            if self._stop.is_set():
                return
            try:
                identifier_name, identifier, status = self._submit(recipient, notification)
            except SmsSendError as exc:
                self.logger.warning(
                    "%s_notification_failed event=%s notification_id=%s recipient_index=%s "
                    "reason=%s http_status=%s provider_code=%s",
                    self._channel,
                    notification.event,
                    notification.notification_id,
                    index,
                    exc.reason,
                    exc.http_status,
                    exc.provider_code,
                )
            except EmailSendError as exc:
                self.logger.warning(
                    "%s_notification_failed event=%s notification_id=%s recipient_index=%s reason=%s smtp_code=%s",
                    self._channel,
                    notification.event,
                    notification.notification_id,
                    index,
                    exc.reason,
                    exc.smtp_code,
                )
            except Exception:
                # Provider exception text can contain credentials, recipients, or message content.
                self.logger.error(
                    "%s_notification_failed event=%s notification_id=%s recipient_index=%s reason=unexpected_error",
                    self._channel,
                    notification.event,
                    notification.notification_id,
                    index,
                )
            else:
                self.logger.info(
                    "%s_notification_submitted event=%s notification_id=%s recipient_index=%s %s=%s status=%s",
                    self._channel,
                    notification.event,
                    notification.notification_id,
                    index,
                    identifier_name,
                    identifier,
                    status,
                )

    def _submit(self, recipient: str, notification: _Notification) -> tuple[str, str, str]:
        raise NotImplementedError


class SmsNotifications(_BackgroundNotifications[SmsSender]):
    def __init__(self, *, enabled: bool, service_start_enabled: bool,
                 sender: SmsSender | None = None, recipients: tuple[str, ...] = ()) -> None:
        super().__init__(enabled=enabled, service_start_enabled=service_start_enabled,
                         channel="sms", sender=sender, recipients=recipients)

    def notify(self, *, event: str, body: str) -> bool:
        return self._enqueue(event=event, body=body)

    def _submit(self, recipient: str, notification: _Notification) -> tuple[str, str, str]:
        assert self.sender is not None
        result = self.sender.send(to_number=recipient, body=notification.body)
        return "message_sid", result.message_sid, result.status


class EmailNotifications(_BackgroundNotifications[EmailSender]):
    def __init__(self, *, enabled: bool, service_start_enabled: bool,
                 sender: EmailSender | None = None, recipients: tuple[str, ...] = ()) -> None:
        super().__init__(enabled=enabled, service_start_enabled=service_start_enabled,
                         channel="email", sender=sender, recipients=recipients)

    def notify(self, *, event: str, subject: str, body: str) -> bool:
        return self._enqueue(event=event, subject=subject, body=body)

    def _submit(self, recipient: str, notification: _Notification) -> tuple[str, str, str]:
        assert self.sender is not None
        result = self.sender.send(to_address=recipient, subject=notification.subject, body=notification.body)
        return "message_id", result.message_id, result.status
