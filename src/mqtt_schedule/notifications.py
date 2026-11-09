from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from queue import Empty, Full, Queue
import threading
from typing import Protocol
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
class _SmsNotification:
    notification_id: str
    event: str
    body: str


class SmsNotifications:
    """Gate every SMS send and perform network work outside the scheduler thread."""

    def __init__(
        self,
        *,
        enabled: bool,
        service_start_enabled: bool,
        sender: SmsSender | None = None,
        recipients: tuple[str, ...] = (),
    ) -> None:
        self.enabled = enabled
        self.service_start_enabled = service_start_enabled
        self.sender = sender
        self.recipients = tuple(dict.fromkeys(recipients))
        self.logger = logging.getLogger("mqtt_schedule.notifications")
        self._queue: Queue[_SmsNotification] = Queue(maxsize=20)
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
            self.logger.info("sms_notification_skipped event=service_start reason=event_disabled")
            return False
        return self.notify(
            event="service_start",
            body=(
                f"MQTT Schedule started on {host_name} (server {source_serial}) "
                f"at {started_at.isoformat(timespec='seconds')}."
            ),
        )

    def notify(self, *, event: str, body: str) -> bool:
        with self._lock:
            if not self.enabled or self._closed:
                return False
            if self.sender is None or not self.recipients:
                self.logger.warning("sms_notification_skipped event=%s reason=not_configured", event)
                return False
            notification = _SmsNotification(uuid4().hex, event, body)
            try:
                self._queue.put_nowait(notification)
            except Full:
                self.logger.warning("sms_notification_skipped event=%s reason=queue_full", event)
                return False
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="mqtt-schedule-sms", daemon=True)
                self._thread.start()
        self.logger.info(
            "sms_notification_queued event=%s notification_id=%s recipient_count=%s",
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
                self.logger.info("sms_worker_stopping reason=request_in_progress")

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

    def _send(self, notification: _SmsNotification) -> None:
        assert self.sender is not None
        for index, recipient in enumerate(self.recipients, start=1):
            if self._stop.is_set():
                return
            try:
                result = self.sender.send(to_number=recipient, body=notification.body)
            except SmsSendError as exc:
                self.logger.warning(
                    "sms_notification_failed event=%s notification_id=%s recipient_index=%s "
                    "reason=%s http_status=%s provider_code=%s",
                    notification.event,
                    notification.notification_id,
                    index,
                    exc.reason,
                    exc.http_status,
                    exc.provider_code,
                )
            except Exception:
                # Provider exception text can contain credentials, recipients, or message content.
                self.logger.error(
                    "sms_notification_failed event=%s notification_id=%s recipient_index=%s reason=unexpected_error",
                    notification.event,
                    notification.notification_id,
                    index,
                )
            else:
                self.logger.info(
                    "sms_notification_submitted event=%s notification_id=%s recipient_index=%s message_sid=%s status=%s",
                    notification.event,
                    notification.notification_id,
                    index,
                    result.message_sid,
                    result.status,
                )
