from __future__ import annotations

from hashlib import sha256
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import threading
from time import monotonic, time
from typing import Callable
from zoneinfo import ZoneInfo

from .app import ControllerRepository
from .input_alerts import FileInputAlertRepository, InputAlertRule
from .notifications import EmailNotifications, SmsNotifications
from .settings import RuntimeSettings


def _finite_number(value: object) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)) or (
        isinstance(value, float) and math.isfinite(value)
    )


def _physical_levels(payload: dict[str, object]) -> dict[int, int] | None:
    count = payload.get("inputCount", 8)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 8:
        return None
    if "inputLevelsBitmap" in payload:
        bitmap = payload["inputLevelsBitmap"]
    elif "inputs" in payload:
        inputs = payload["inputs"]
        if not isinstance(inputs, dict):
            return None
        levels = {}
        for index in range(count):
            item = inputs.get(f"input_{index}")
            if not isinstance(item, dict):
                continue
            reported_index = item.get("index", index)
            if isinstance(reported_index, bool) or not isinstance(reported_index, int) or reported_index != index:
                continue
            level = item.get("level")
            if isinstance(level, int) and not isinstance(level, bool) and level in (0, 1):
                levels[index] = level
        return levels or None
    else:
        bitmap = payload.get("input_ports")
    if isinstance(bitmap, bool) or not isinstance(bitmap, int) or not 0 <= bitmap <= 255:
        return None
    return {index: (bitmap >> index) & 1 for index in range(count)}


def _inside_window(rule: InputAlertRule, seconds: int) -> bool:
    start, end = rule.start_time_seconds, rule.end_time_seconds
    if start == end == 0:
        return True
    if start < end:
        return start <= seconds < end
    return seconds >= start or seconds < end


class InputAlertReportStore:
    """Bounded restart-safe suppression, not a notification delivery outbox."""

    MAX_REPORTS = 1024
    KEEP_SECONDS = 86400

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def claim(self, *, source_serial: str, category: str, report_id: str, now: float) -> bool:
        key = sha256(json.dumps([source_serial, category, report_id]).encode("utf-8")).hexdigest()
        with self._lock:
            try:
                if self.path.stat().st_size > 256 * 1024:
                    raise ValueError("Oversized input-alert state")
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                payload = {"version": 1, "reports": {}}
            if (not isinstance(payload, dict) or payload.get("version") != 1
                    or not isinstance(payload.get("reports"), dict)):
                raise ValueError("Invalid input-alert state")
            reports = payload["reports"]
            for saved_key, saved_at in reports.items():
                if (not isinstance(saved_key, str) or len(saved_key) != 64
                        or any(char not in "0123456789abcdef" for char in saved_key)
                        or not _finite_number(saved_at)):
                    raise ValueError("Invalid input-alert state entry")
            reports = {item: stamp for item, stamp in reports.items() if stamp >= now - self.KEEP_SECONDS}
            if key in reports:
                return False
            reports[key] = now
            reports = dict(sorted(reports.items(), key=lambda item: item[1])[-self.MAX_REPORTS:])
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "reports": reports}, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            return True


class InputAlertProcessor:
    def __init__(
        self, *, settings: RuntimeSettings, controller_repository: ControllerRepository,
        sms_notifications: SmsNotifications | None = None,
        email_notifications: EmailNotifications | None = None,
        dry_run: bool = False, clock: Callable[[], float] = time,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        self.settings = settings
        self.controllers = controller_repository
        self.sms = sms_notifications
        self.email = email_notifications
        self.dry_run = dry_run
        self.clock = clock
        self.monotonic_clock = monotonic_clock
        self.timezone = ZoneInfo(settings.timezone_name)
        self._dispatch_lock = threading.Lock()
        self._cooldowns: dict[tuple[str, str, str, int, str, str], float] = {}
        self.rules = FileInputAlertRepository(settings.input_alerts_file, controller_file=settings.controller_file)
        self.store = InputAlertReportStore(settings.input_alert_state_file)
        self.logger = logging.getLogger("mqtt_schedule.input_alerts")

    def handle_response(self, *, source_serial: str, payload: dict[str, object], retained: bool = False) -> None:
        if not self.settings.input_alerts_enabled or self.dry_run:
            return
        if retained:
            self.logger.info("input_alert_report_ignored reason=retained source_serial=%s", source_serial)
            return
        positive, negative = payload.get("positive_edges", 0), payload.get("negative_edges", 0)
        if any(isinstance(mask, bool) or not isinstance(mask, int) or not 0 <= mask <= 255
               for mask in (positive, negative)):
            self.logger.warning("input_alert_report_ignored reason=invalid_edge_masks source_serial=%s", source_serial)
            return
        levels = _physical_levels(payload)
        if not positive and not negative and levels is None:
            if "inputLevelsBitmap" in payload or "inputs" in payload:
                self.logger.warning("input_alert_report_ignored reason=invalid_levels source_serial=%s", source_serial)
            return
        category, report_id, timestamp = payload.get("inputs_category"), payload.get("_iD"), payload.get("unixTime")
        if (not isinstance(category, str) or not category.strip() or len(category) > 128
                or not isinstance(report_id, str) or not report_id.strip() or len(report_id) > 128
                or any(ord(char) < 32 or ord(char) == 127 for char in category + report_id)
                or not _finite_number(timestamp)):
            self.logger.warning("input_alert_report_ignored reason=invalid_metadata source_serial=%s", source_serial)
            return
        now = self.clock()
        if not now - self.settings.input_alerts_max_age_seconds <= timestamp <= now + 60:
            self.logger.warning("input_alert_report_ignored reason=stale_or_future source_serial=%s report_id=%s",
                                source_serial, report_id)
            return
        try:
            if not any(controller.enabled and controller.name_link == source_serial
                       for controller in self.controllers.list_controllers()):
                self.logger.info("input_alert_report_ignored reason=controller_disabled_or_unknown source_serial=%s", source_serial)
                return
            rules, disabled_keys = self.rules.load_configuration()
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.logger.warning("input_alert_report_ignored reason=configuration_unavailable source_serial=%s", source_serial)
            return
        level_rules = [rule for rule in rules if rule.controller_serial == source_serial
                       and rule.input_category == category and rule.effective_trigger_source in ("levelHigh", "levelLow")]
        if not positive and not negative and not level_rules:
            return
        with self._dispatch_lock:
            try:
                if not self.store.claim(source_serial=source_serial, category=category, report_id=report_id, now=now):
                    self.logger.info("input_alert_report_ignored reason=duplicate source_serial=%s report_id=%s", source_serial, report_id)
                    return
            except (OSError, ValueError):
                self.logger.error("input_alert_report_ignored reason=state_unavailable source_serial=%s report_id=%s",
                                  source_serial, report_id)
                return
            active_keys = {self._cooldown_key(rule, channel) for rule in rules
                           if rule.notification_cooldown_seconds > 0 for channel in rule.channels}
            self._cooldowns = {key: stamp for key, stamp in self._cooldowns.items() if key in active_keys}
            local_now = datetime.fromtimestamp(now, self.timezone)
            seconds = local_now.hour * 3600 + local_now.minute * 60 + local_now.second
            by_key = {(rule.controller_serial, rule.input_category, rule.input_index, rule.match_source): rule for rule in rules}
            # Claim before dispatch: redelivery must not replay suppressed or already queued events.
            for edge, mask in (("positive", positive), ("negative", negative)):
                for index in range(8):
                    if not mask & (1 << index):
                        continue
                    key = (source_serial, category, index, edge)
                    rule = by_key.get(key)
                    if rule is None:
                        if key not in disabled_keys:
                            self.logger.warning(
                                "input_alert_rule_missing source_serial=%s inputs_category=%s input_index=%s edge=%s report_id=%s",
                                source_serial, category, index, edge, report_id,
                            )
                        continue
                    self._dispatch(rule, report_id=report_id, seconds=seconds)
            if level_rules and levels is None:
                self.logger.warning("input_alert_levels_ignored reason=invalid_levels source_serial=%s report_id=%s",
                                    source_serial, report_id)
            for rule in level_rules:
                expected = 1 if rule.effective_trigger_source == "levelHigh" else 0
                if levels is not None and levels.get(rule.input_index) == expected:
                    self._dispatch(rule, report_id=report_id, seconds=seconds)

    @staticmethod
    def _cooldown_key(rule: InputAlertRule, channel: str) -> tuple[str, str, str, int, str, str]:
        return (rule.record_id, rule.controller_serial, rule.input_category, rule.input_index,
                rule.effective_trigger_source, channel)

    def _dispatch(self, rule: InputAlertRule, *, report_id: str, seconds: int) -> None:
        trigger = rule.effective_trigger_source
        if not _inside_window(rule, seconds):
            self.logger.info("input_alert_skipped reason=outside_window rule_id=%s trigger_source=%s report_id=%s",
                             rule.record_id, trigger, report_id)
            return
        event = "input_edge" if rule.edge else "input_level"
        detail = f"edge: {rule.edge}" if rule.edge else f"trigger: {trigger}"
        body = (f"{rule.message}\nController: {rule.controller_name} ({rule.controller_serial}); "
                f"category: {rule.input_category}; input: {rule.input_index}; {detail}; report: {report_id}")
        for channel in rule.channels:
            key = self._cooldown_key(rule, channel)
            elapsed_now = self.monotonic_clock()
            previous = self._cooldowns.get(key)
            if previous is not None and elapsed_now - previous < rule.notification_cooldown_seconds:
                self.logger.info("input_alert_skipped reason=cooldown rule_id=%s trigger_source=%s channel=%s report_id=%s",
                                 rule.record_id, trigger, channel, report_id)
                continue
            queued = False
            if channel == "sms" and self.settings.sms_enabled and self.sms is not None:
                queued = self.sms.notify(event=event, body=body)
            elif channel == "email" and self.settings.email_enabled and self.email is not None:
                queued = self.email.notify(event=event, subject="MQTT Schedule input alert", body=body)
            if queued and rule.notification_cooldown_seconds > 0:
                self._cooldowns[key] = self.monotonic_clock()
            self.logger.info(
                "input_alert_dispatch source_serial=%s inputs_category=%s input_index=%s edge=%s "
                "report_id=%s rule_id=%s channel=%s queued=%s trigger_source=%s",
                rule.controller_serial, rule.input_category, rule.input_index, rule.edge,
                report_id, rule.record_id, channel, queued, trigger,
            )
