from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .airtable_repositories import AirtableFileValidationSummary, AirtableValidationIssue
from .airtable_values import enabled_value


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

        input_index = fields.get("inputIndex")
        if (isinstance(input_index, bool) or not isinstance(input_index, (int, float))
                or not 0 <= input_index <= 7 or int(input_index) != input_index):
            error(prefix + "inputIndex must be an integer from 0 through 7.")
        edge = fields.get("edge")
        if edge not in ("positive", "negative"):
            error(prefix + "edge must be positive or negative.")
        channels = fields.get("channels", [])
        if not isinstance(channels, list) or any(channel not in ("sms", "email") for channel in channels):
            error(prefix + "channels must be a multiple-select list containing only sms and/or email.")

        if len(issues) != errors_before:
            continue
        key = (controller_id, category.strip(), int(input_index), edge)
        if key in seen_keys:
            error(prefix + "another enabled rule already matches this controller, category, input, and edge.")
            continue
        seen_keys.add(key)
        serial, controller_name = controllers[controller_id]
        rules.append(InputAlertRule(
            record_id=record_id,
            name=name.strip(),
            controller_record_id=controller_id,
            controller_serial=serial,
            controller_name=controller_name,
            input_category=category.strip(),
            input_index=int(input_index),
            edge=edge,
            channels=tuple(dict.fromkeys(channels)),
            message=message.strip(),
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
