from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .app import ControllerRepository, ScheduleRepository
from .domain import ControllerTarget, ScheduleEntry


@dataclass(frozen=True)
class AirtableRecord:
    record_id: str
    fields: dict[str, Any]


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
