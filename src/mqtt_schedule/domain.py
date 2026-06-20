from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Season(str, Enum):
    SPRING = "Spring"
    SUMMER = "Summer"
    FALL = "Fall"
    WINTER = "Winter"
    ALL = "All_seasons"


@dataclass(frozen=True)
class ScheduleEntry:
    record_id: str
    enabled: bool
    season_names: list[str]
    day_of_week: list[str]
    start_time: int | None
    end_time: int | None
    duration_on: int | None
    zone_number: str
    group_select: list[str]
    zone_category: str
    output_type: str


@dataclass(frozen=True)
class ControllerTarget:
    name: str
    name_link: str
    enabled: bool
    group_select: list[str]
    ip_address: str | None = None


@dataclass(frozen=True)
class SunTimes:
    sunrise_seconds: int
    sunset_seconds: int


@dataclass(frozen=True)
class IrrigationDecision:
    allow: bool
    reason: str
    metrics: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DueCommand:
    schedule_record_id: str
    controller_links: list[str]
    output_type: str
    output_index: int
    on: bool
    timer_ms: int
    group_select: list[str]
    zone_category: str
    evaluated_at: datetime


@dataclass(frozen=True)
class ScheduleExplanation:
    schedule_record_id: str
    enabled: bool
    season_match: bool
    day_match: bool
    output_index: int | None
    timer_ms: int
    output_type: str
    zone_category: str
    group_select: list[str]
    controller_links: list[str]
    irrigation_allowed: bool | None
    irrigation_reason: str | None
    matched: bool
    skip_reason: str | None
