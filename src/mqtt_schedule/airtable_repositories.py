from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .app import ControllerRepository, ScheduleRepository
from .domain import ControllerTarget, ScheduleEntry


@dataclass(frozen=True)
class AirtableRecord:
    record_id: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class AirtableValidationIssue:
    severity: str
    message: str


@dataclass(frozen=True)
class AirtableFileValidationSummary:
    file_kind: str
    path: Path
    record_count: int
    valid_count: int
    issues: list[AirtableValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


class AirtableJsonFile:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load_records(self) -> list[AirtableRecord]:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        out: list[AirtableRecord] = []
        for item in raw.get("records", []):
            out.append(
                AirtableRecord(
                    record_id=str(item.get("id", "")),
                    fields=dict(item.get("fields") or {}),
                )
            )
        return out

    def load_raw_json(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))


class FileScheduleRepository(ScheduleRepository):
    def __init__(self, path: str | Path) -> None:
        self.file = AirtableJsonFile(path)

    def list_schedules(self) -> list[ScheduleEntry]:
        schedules: list[ScheduleEntry] = []
        for record in self.file.load_records():
            fields = record.fields
            zone_number = _first_list_value(fields.get("zoneNumber"))
            if not zone_number:
                continue

            schedules.append(
                ScheduleEntry(
                    record_id=record.record_id,
                    enabled=_bool_value(fields.get("enabled")),
                    season_names=_string_list(fields.get("seasonNames")),
                    day_of_week=_string_list(fields.get("day_of_week")),
                    start_time=_int_or_none(fields.get("start_time")),
                    end_time=_int_or_none(fields.get("end_time")),
                    duration_on=_int_or_none(fields.get("duration_on")),
                    zone_number=zone_number,
                    group_select=_string_list(fields.get("groupSelect")),
                    zone_category=_string_value(fields.get("zone_category"), default="Unknown"),
                    output_type=_first_list_value(fields.get("output-type"), default="output-general"),
                )
            )
        return schedules


class FileControllerRepository(ControllerRepository):
    def __init__(self, path: str | Path) -> None:
        self.file = AirtableJsonFile(path)

    def list_controllers(self) -> list[ControllerTarget]:
        controllers: list[ControllerTarget] = []
        for record in self.file.load_records():
            fields = record.fields
            name = _string_value(fields.get("Name"))
            name_link = _string_value(fields.get("nameLink"))
            if not name or not name_link:
                continue

            controllers.append(
                ControllerTarget(
                    name=name,
                    name_link=name_link,
                    enabled=_bool_value(fields.get("enabled")),
                    group_select=_string_list(fields.get("groupSelect")),
                    ip_address=_string_or_none(fields.get("ipAddress")),
                )
            )
        return controllers


def validate_schedule_file(path: str | Path) -> AirtableFileValidationSummary:
    airtable_file = AirtableJsonFile(path)
    issues: list[AirtableValidationIssue] = []
    raw = _load_raw_with_issues(airtable_file, issues)
    records = _records_from_raw(raw, issues)
    valid_count = 0

    for item in records:
        fields = dict(item.get("fields") or {})
        zone_number = _first_list_value(fields.get("zoneNumber"))
        if not zone_number:
            continue
        valid_count += 1

    if records and valid_count == 0:
        issues.append(
            AirtableValidationIssue(
                severity="error",
                message="No schedule records contained a usable zoneNumber value.",
            )
        )

    return AirtableFileValidationSummary(
        file_kind="schedule",
        path=Path(path),
        record_count=len(records),
        valid_count=valid_count,
        issues=issues,
    )


def validate_controller_file(path: str | Path) -> AirtableFileValidationSummary:
    airtable_file = AirtableJsonFile(path)
    issues: list[AirtableValidationIssue] = []
    raw = _load_raw_with_issues(airtable_file, issues)
    records = _records_from_raw(raw, issues)
    valid_count = 0

    for item in records:
        fields = dict(item.get("fields") or {})
        name = _string_value(fields.get("Name"))
        name_link = _string_value(fields.get("nameLink"))
        if not name or not name_link:
            continue
        valid_count += 1

    if records and valid_count == 0:
        issues.append(
            AirtableValidationIssue(
                severity="error",
                message="No controller records contained both Name and nameLink.",
            )
        )

    return AirtableFileValidationSummary(
        file_kind="controller",
        path=Path(path),
        record_count=len(records),
        valid_count=valid_count,
        issues=issues,
    )


def _load_raw_with_issues(
    airtable_file: AirtableJsonFile,
    issues: list[AirtableValidationIssue],
) -> dict[str, Any]:
    try:
        raw = airtable_file.load_raw_json()
    except FileNotFoundError:
        issues.append(
            AirtableValidationIssue(
                severity="error",
                message=f"File not found: {airtable_file.path}",
            )
        )
        return {}
    except json.JSONDecodeError as exc:
        issues.append(
            AirtableValidationIssue(
                severity="error",
                message=f"Invalid JSON: {exc}",
            )
        )
        return {}

    if not isinstance(raw, dict):
        issues.append(
            AirtableValidationIssue(
                severity="error",
                message="Top-level JSON value must be an object containing a records array.",
            )
        )
        return {}
    return raw


def _records_from_raw(
    raw: dict[str, Any],
    issues: list[AirtableValidationIssue],
) -> list[dict[str, Any]]:
    records = raw.get("records")
    if records is None:
        issues.append(
            AirtableValidationIssue(
                severity="error",
                message="Top-level object is missing the records key.",
            )
        )
        return []
    if not isinstance(records, list):
        issues.append(
            AirtableValidationIssue(
                severity="error",
                message="The records value must be a list.",
            )
        )
        return []
    if not records:
        issues.append(
            AirtableValidationIssue(
                severity="warning",
                message="The records list is empty.",
            )
        )
    return [item for item in records if isinstance(item, dict)]


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _first_list_value(value: Any, default: str = "") -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, str):
            return first
    return default


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_value(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value
    return default


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
