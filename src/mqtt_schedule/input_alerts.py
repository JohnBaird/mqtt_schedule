from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .airtable_repositories import AirtableFileValidationSummary, AirtableValidationIssue
from .airtable_values import enabled_value


_EDGE_TRIGGERS = {"positive": "positiveEdge", "negative": "negativeEdge"}
_TRIGGER_SOURCES = ("positiveEdge", "negativeEdge", "levelHigh", "levelLow")


@dataclass(frozen=True)
class InputAlertRule:
    record_id: str
    name: str
    controller_record_id: str
    controller_serial: str
    controller_name: str
    input_category: str
    input_index: int
    edge: str
    channels: tuple[str, ...]
    message: str
    trigger_source: str = ""
    notification_cooldown_seconds: int = 0
    start_time_seconds: int = 0
    end_time_seconds: int = 0

    @property
    def effective_trigger_source(self) -> str:
        return self.trigger_source or _EDGE_TRIGGERS.get(self.edge, "")

    @property
    def match_source(self) -> str:
        return self.edge or self.effective_trigger_source


def _input_index(value: object) -> int:
    if isinstance(value, str) and len(value) == 1 and "0" <= value <= "7":
        return int(value)
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 <= value <= 7 or int(value) != value):
        raise ValueError("inputIndex must be an integer from 0 through 7 or its single-digit text value.")
    return int(value)


def _trigger_source(fields: dict[str, object]) -> str:
    legacy = fields.get("edge")
    trigger = fields.get("triggerSource")
    if "triggerSource" not in fields:
        if legacy not in ("positive", "negative"):
            raise ValueError("triggerSource must be positiveEdge, negativeEdge, levelHigh, or levelLow; legacy edge must be positive or negative.")
        return _EDGE_TRIGGERS[legacy]
    if trigger not in _TRIGGER_SOURCES:
        raise ValueError("triggerSource must be positiveEdge, negativeEdge, levelHigh, or levelLow.")
    if "edge" in fields and (legacy not in ("positive", "negative") or _EDGE_TRIGGERS[legacy] != trigger):
        raise ValueError("edge and triggerSource conflict; remove the legacy edge field when migrating.")
    return trigger


def _seconds(value: object, name: str, maximum: int | None = None) -> int:
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0
            or (maximum is not None and value > maximum)):
        raise ValueError(f"{name} must be a nonnegative whole number of seconds" +
                         (f" no greater than {maximum}." if maximum is not None else "."))
    try:
        seconds = int(value)
    except (ValueError, OverflowError):
        raise ValueError(f"{name} must be a finite whole number of seconds.") from None
    if seconds != value:
        raise ValueError(f"{name} must be a whole number of seconds.")
    return seconds


def _controller_index(path: Path) -> dict[str, tuple[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("Invalid controller export")
    index: dict[str, tuple[str, str]] = {}
    seen_ids: set[str] = set()
    for record in payload["records"]:
        if not isinstance(record, dict) or not isinstance(record.get("fields"), dict):
            raise ValueError("Invalid controller record")
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id or record_id in seen_ids:
            raise ValueError("Invalid or duplicate controller record ID")
        seen_ids.add(record_id)
        fields = record["fields"]
        serial, name = fields.get("nameLink"), fields.get("Name")
        if (isinstance(serial, str) and serial.isascii() and serial.isdigit()
                and isinstance(name, str) and name.strip()):
            index[record_id] = (serial, name.strip())
    return index


def _parse_rules(payload: object, controller_file: Path) -> tuple[int, list[InputAlertRule], list[AirtableValidationIssue]]:
    issues: list[AirtableValidationIssue] = []
    rules: list[InputAlertRule] = []

    def error(message: str) -> None:
        issues.append(AirtableValidationIssue(severity="error", message=message))

    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        error("Expected an Airtable object with a records array.")
        return 0, rules, issues

    controllers: dict[str, tuple[str, str]] | None = None
    controller_load_failed = False
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, int, str]] = set()
    records = payload["records"]
    for number, record in enumerate(records, start=1):
        prefix = f"Record {number}: "
        if not isinstance(record, dict) or not isinstance(record.get("fields"), dict):
            error(prefix + "id and fields objects are required.")
            continue
        record_id, fields = record.get("id"), record["fields"]
        if not isinstance(record_id, str) or not record_id.strip() or record_id in seen_ids:
            error(prefix + "id must be a nonempty unique string.")
            continue
        seen_ids.add(record_id)
        if not enabled_value(fields.get("enabled")):
            continue

        if controllers is None and not controller_load_failed:
            try:
                controllers = _controller_index(controller_file)
            except (OSError, ValueError):
                error("Controller export is missing or invalid; refresh controller config before enabling alert rules.")
                controller_load_failed = True
        if controller_load_failed:
            continue
        assert controllers is not None

        errors_before = len(issues)
        name, category, message = fields.get("Name"), fields.get("inputCategory"), fields.get("message")
        for field_name, value in (("Name", name), ("inputCategory", category), ("message", message)):
            if not isinstance(value, str) or not value.strip():
                error(prefix + field_name + " must be nonempty text.")
        links = fields.get("controller")
        controller_id = None
        if not isinstance(links, list) or len(links) != 1 or not isinstance(links[0], str):
            error(prefix + "controller must link to exactly one irrigation-config record.")
        elif links[0] not in controllers:
            error(prefix + "controller link is not in the local controller export; refresh controller config.")
        else:
            controller_id = links[0]

        try:
            input_index = _input_index(fields.get("inputIndex"))
        except ValueError as exc:
            error(prefix + str(exc))
        try:
            trigger = _trigger_source(fields)
            edge = {"positiveEdge": "positive", "negativeEdge": "negative"}.get(trigger, "")
        except ValueError as exc:
            error(prefix + str(exc))
        try:
            cooldown = _seconds(fields.get("notificationCooldown", fields.get("cycleTime", 0)), "notificationCooldown")
            if ("notificationCooldown" in fields and "cycleTime" in fields
                    and _seconds(fields["cycleTime"], "cycleTime") != cooldown):
                raise ValueError("notificationCooldown and legacy cycleTime conflict.")
            start = _seconds(fields.get("startTime", 0), "startTime", 86399)
            end = _seconds(fields.get("endTime", 0), "endTime", 86400)
            if start == end and start != 0:
                raise ValueError("Equal startTime/endTime is only allowed for 0/0 (all day).")
        except ValueError as exc:
            error(prefix + str(exc))
        channels = fields.get("channels", [])
        if not isinstance(channels, list) or any(channel not in ("sms", "email") for channel in channels):
            error(prefix + "channels must be a multiple-select list containing only sms and/or email.")

        if len(issues) != errors_before:
            continue
        serial, controller_name = controllers[controller_id]
        key = (serial, category.strip(), input_index, edge or trigger)
        if key in seen_keys:
            error(prefix + "another enabled rule already matches this controller, category, input, and trigger.")
            continue
        seen_keys.add(key)
        rules.append(InputAlertRule(
            record_id=record_id,
            name=name.strip(),
            controller_record_id=controller_id,
            controller_serial=serial,
            controller_name=controller_name,
            input_category=category.strip(),
            input_index=input_index,
            edge=edge,
            channels=tuple(dict.fromkeys(channels)),
            message=message.strip(),
            trigger_source=trigger,
            notification_cooldown_seconds=cooldown,
            start_time_seconds=start,
            end_time_seconds=end,
        ))
    return len(records), rules, issues


def validate_input_alerts_payload(
    payload: object, *, controller_file: str | Path, path: str | Path,
) -> AirtableFileValidationSummary:
    count, rules, issues = _parse_rules(payload, Path(controller_file))
    return AirtableFileValidationSummary("input_alerts", Path(path), count, len(rules), issues)


def validate_input_alerts_file(path: str | Path, *, controller_file: str | Path) -> AirtableFileValidationSummary:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AirtableFileValidationSummary("input_alerts", Path(path), 0, 0, [
            AirtableValidationIssue("error", "Input-alerts JSON file is missing, unreadable, or invalid JSON."),
        ])
    return validate_input_alerts_payload(payload, controller_file=controller_file, path=path)


class FileInputAlertRepository:
    """Resolve enabled rules; execution must separately check current controller/channel enablement."""

    def __init__(self, path: str | Path, *, controller_file: str | Path) -> None:
        self.path = Path(path)
        self.controller_file = Path(controller_file)

    def list_rules(self) -> list[InputAlertRule]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        _, rules, issues = _parse_rules(payload, self.controller_file)
        if issues:
            raise ValueError(" ".join(issue.message for issue in issues))
        return rules

    def load_configuration(self) -> tuple[list[InputAlertRule], set[tuple[str, str, int, str]]]:
        """Read one snapshot, retaining explicit disabled keys for missing-rule diagnostics."""
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        _, rules, issues = _parse_rules(payload, self.controller_file)
        if issues:
            raise ValueError("Invalid input-alert configuration")
        disabled_keys: set[tuple[str, str, int, str]] = set()
        controllers = _controller_index(self.controller_file) if payload["records"] else {}
        for record in payload["records"]:
            fields = record["fields"]
            if enabled_value(fields.get("enabled")):
                continue
            links = fields.get("controller")
            category = fields.get("inputCategory")
            if (not isinstance(links, list) or len(links) != 1 or not isinstance(links[0], str)
                    or links[0] not in controllers or not isinstance(category, str) or not category.strip()):
                continue
            try:
                index = _input_index(fields.get("inputIndex"))
                trigger = _trigger_source(fields)
            except ValueError:
                continue
            match_source = {"positiveEdge": "positive", "negativeEdge": "negative"}.get(trigger, trigger)
            disabled_keys.add((controllers[links[0]][0], category.strip(), index, match_source))
        return rules, disabled_keys
