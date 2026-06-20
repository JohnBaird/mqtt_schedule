from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .domain import ControllerTarget, DueCommand, IrrigationDecision, ScheduleEntry, ScheduleExplanation, Season, SunTimes


IrrigationPolicy = Callable[[datetime], IrrigationDecision]


@dataclass
class SchedulerConfig:
    hemisphere: str = "north"
    use_duration_sunrise: bool = True
    use_duration_sunset: bool = False


class ScheduleEvaluator:
    def __init__(self, config: SchedulerConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        now: datetime,
        schedules: list[ScheduleEntry],
        controllers: list[ControllerTarget],
        sun_times: SunTimes | None = None,
        irrigation_policy: IrrigationPolicy | None = None,
    ) -> list[DueCommand]:
        return [item.command for item in self.evaluate_with_explanations(
            now=now,
            schedules=schedules,
            controllers=controllers,
            sun_times=sun_times,
            irrigation_policy=irrigation_policy,
        ) if item.command is not None]

    def evaluate_with_explanations(
        self,
        *,
        now: datetime,
        schedules: list[ScheduleEntry],
        controllers: list[ControllerTarget],
        sun_times: SunTimes | None = None,
        irrigation_policy: IrrigationPolicy | None = None,
    ) -> list[EvaluationResult]:
        current_season = self._current_season_name(now, self.config.hemisphere)
        results: list[EvaluationResult] = []
        now_seconds = self._seconds_since_midnight(now)

        for schedule in schedules:
            base = {
                "schedule_record_id": schedule.record_id,
                "enabled": schedule.enabled,
                "output_type": schedule.output_type.lower(),
                "zone_category": schedule.zone_category,
                "group_select": [group.lower() for group in schedule.group_select],
            }
            if not schedule.enabled:
                results.append(EvaluationResult(
                    command=None,
                    explanation=ScheduleExplanation(
                        **base,
                        season_match=False,
                        day_match=False,
                        output_index=None,
                        timer_ms=0,
                        controller_links=[],
                        irrigation_allowed=None,
                        irrigation_reason=None,
                        matched=False,
                        skip_reason="disabled",
                    ),
                ))
                continue

            season_match = self._season_matches(schedule.season_names, current_season)
            if not season_match:
                results.append(EvaluationResult(
                    command=None,
                    explanation=ScheduleExplanation(
                        **base,
                        season_match=False,
                        day_match=False,
                        output_index=None,
                        timer_ms=0,
                        controller_links=[],
                        irrigation_allowed=None,
                        irrigation_reason=None,
                        matched=False,
                        skip_reason="season_mismatch",
                    ),
                ))
                continue

            day_match = self._day_matches(schedule.day_of_week, now)
            if not day_match:
                results.append(EvaluationResult(
                    command=None,
                    explanation=ScheduleExplanation(
                        **base,
                        season_match=True,
                        day_match=False,
                        output_index=None,
                        timer_ms=0,
                        controller_links=[],
                        irrigation_allowed=None,
                        irrigation_reason=None,
                        matched=False,
                        skip_reason="day_mismatch",
                    ),
                ))
                continue

            output_index = self._output_index_from_zone_number(schedule.zone_number)
            if output_index is None:
                results.append(EvaluationResult(
                    command=None,
                    explanation=ScheduleExplanation(
                        **base,
                        season_match=True,
                        day_match=True,
                        output_index=None,
                        timer_ms=0,
                        controller_links=[],
                        irrigation_allowed=None,
                        irrigation_reason=None,
                        matched=False,
                        skip_reason="invalid_zone_number",
                    ),
                ))
                continue

            timer_ms = self._timer_ms_for_schedule(
                now_seconds=now_seconds,
                schedule=schedule,
                sun_times=sun_times,
            )
            if timer_ms <= 0:
                results.append(EvaluationResult(
                    command=None,
                    explanation=ScheduleExplanation(
                        **base,
                        season_match=True,
                        day_match=True,
                        output_index=output_index,
                        timer_ms=timer_ms,
                        controller_links=[],
                        irrigation_allowed=None,
                        irrigation_reason=None,
                        matched=False,
                        skip_reason="inactive_time_window",
                    ),
                ))
                continue

            irrigation_allowed: bool | None = None
            irrigation_reason: str | None = None
            if schedule.output_type.lower() == "output-irrigation" and irrigation_policy is not None:
                decision = irrigation_policy(now)
                irrigation_allowed = decision.allow
                irrigation_reason = decision.reason
                if not decision.allow:
                    results.append(EvaluationResult(
                        command=None,
                        explanation=ScheduleExplanation(
                            **base,
                            season_match=True,
                            day_match=True,
                            output_index=output_index,
                            timer_ms=timer_ms,
                            controller_links=[],
                            irrigation_allowed=irrigation_allowed,
                            irrigation_reason=irrigation_reason,
                            matched=False,
                            skip_reason="irrigation_blocked",
                        ),
                    ))
                    continue

            controller_links = self._matching_controller_links(schedule.group_select, controllers)
            if not controller_links:
                results.append(EvaluationResult(
                    command=None,
                    explanation=ScheduleExplanation(
                        **base,
                        season_match=True,
                        day_match=True,
                        output_index=output_index,
                        timer_ms=timer_ms,
                        controller_links=[],
                        irrigation_allowed=irrigation_allowed,
                        irrigation_reason=irrigation_reason,
                        matched=False,
                        skip_reason="no_matching_controllers",
                    ),
                ))
                continue

            command = DueCommand(
                schedule_record_id=schedule.record_id,
                controller_links=controller_links,
                output_type=schedule.output_type.lower(),
                output_index=output_index,
                on=True,
                timer_ms=timer_ms,
                group_select=[group.lower() for group in schedule.group_select],
                zone_category=schedule.zone_category,
                evaluated_at=now,
            )
            results.append(EvaluationResult(
                command=command,
                explanation=ScheduleExplanation(
                    **base,
                    season_match=True,
                    day_match=True,
                    output_index=output_index,
                    timer_ms=timer_ms,
                    controller_links=controller_links,
                    irrigation_allowed=irrigation_allowed,
                    irrigation_reason=irrigation_reason,
                    matched=True,
                    skip_reason=None,
                ),
            ))

        return results

    @staticmethod
    def _seconds_since_midnight(now: datetime) -> int:
        return now.hour * 3600 + now.minute * 60 + now.second

    @staticmethod
    def _season_matches(season_names: list[str], current_season: str) -> bool:
        if not season_names:
            return False
        return Season.ALL.value in season_names or current_season in season_names

    @staticmethod
    def _day_matches(day_rules: list[str], now: datetime) -> bool:
        if not day_rules:
            return False

        rule = day_rules[0]
        if rule == "Every_day":
            return True

        is_weekday = now.weekday() < 5
        day_of_month = now.day

        if rule == "Week_days_even":
            return is_weekday and day_of_month % 2 == 0
        if rule == "Week_days_odd":
            return is_weekday and day_of_month % 2 == 1

        return rule in (now.strftime("%A"), now.strftime("%a"))

    @staticmethod
    def _output_index_from_zone_number(zone_number: str) -> int | None:
        match = re.search(r"(\d+)\s*$", zone_number)
        if not match:
            return None
        return int(match.group(1)) - 1

    def _timer_ms_for_schedule(
        self,
        *,
        now_seconds: int,
        schedule: ScheduleEntry,
        sun_times: SunTimes | None,
    ) -> int:
        if schedule.zone_category.lower() in {"sunrise", "sunset"}:
            return self._sun_event_timer_ms(
                now_seconds=now_seconds,
                schedule=schedule,
                sun_times=sun_times,
            )
        return self._wall_clock_timer_ms(
            now_seconds=now_seconds,
            start_time=schedule.start_time,
            end_time=schedule.end_time,
        )

    def _sun_event_timer_ms(
        self,
        *,
        now_seconds: int,
        schedule: ScheduleEntry,
        sun_times: SunTimes | None,
    ) -> int:
        if sun_times is None:
            return 0

        is_sunrise = schedule.zone_category.lower() == "sunrise"
        start_seconds = sun_times.sunrise_seconds if is_sunrise else sun_times.sunset_seconds
        use_duration = self.config.use_duration_sunrise if is_sunrise else self.config.use_duration_sunset

        if use_duration:
            if not schedule.duration_on or schedule.duration_on <= 0:
                return 0
            end_seconds = start_seconds + schedule.duration_on
        else:
            if schedule.end_time is None or schedule.end_time <= 0:
                return 0
            end_seconds = schedule.end_time

        if now_seconds < start_seconds or now_seconds >= end_seconds:
            return 0

        return (end_seconds - now_seconds) * 1000

    @staticmethod
    def _wall_clock_timer_ms(*, now_seconds: int, start_time: int | None, end_time: int | None) -> int:
        if start_time is None or end_time is None or start_time == end_time:
            return 0

        if end_time > start_time:
            if start_time <= now_seconds < end_time:
                return (end_time - now_seconds) * 1000
            return 0

        if now_seconds >= start_time:
            return ((86400 - now_seconds) + end_time) * 1000
        if now_seconds < end_time:
            return (end_time - now_seconds) * 1000
        return 0

    @staticmethod
    def _matching_controller_links(
        schedule_groups: list[str],
        controllers: list[ControllerTarget],
    ) -> list[str]:
        schedule_group_set = {group.lower() for group in schedule_groups}
        links: list[str] = []
        for controller in controllers:
            if not controller.enabled:
                continue
            controller_group_set = {group.lower() for group in controller.group_select}
            if schedule_group_set.intersection(controller_group_set):
                links.append(controller.name_link)
        return links

    @staticmethod
    def _current_season_name(now: datetime, hemisphere: str) -> str:
        month_day = now.month * 100 + now.day
        if 320 < month_day < 621:
            season = Season.SPRING.value
        elif 620 < month_day < 923:
            season = Season.SUMMER.value
        elif 922 < month_day < 1223:
            season = Season.FALL.value
        else:
            season = Season.WINTER.value

        if hemisphere.lower() != "north":
            mapping = {
                Season.SPRING.value: Season.FALL.value,
                Season.SUMMER.value: Season.WINTER.value,
                Season.FALL.value: Season.SPRING.value,
                Season.WINTER.value: Season.SUMMER.value,
            }
            season = mapping[season]

        return season


@dataclass(frozen=True)
class EvaluationResult:
    command: DueCommand | None
    explanation: ScheduleExplanation
