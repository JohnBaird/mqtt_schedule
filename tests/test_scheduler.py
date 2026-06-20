from datetime import datetime

from mqtt_schedule.domain import ControllerTarget, IrrigationDecision, ScheduleEntry, SunTimes
from mqtt_schedule.scheduler import ScheduleEvaluator, SchedulerConfig


def make_schedule(**overrides) -> ScheduleEntry:
    base = {
        "record_id": "rec-1",
        "enabled": True,
        "season_names": ["All_seasons"],
        "day_of_week": ["Every_day"],
        "start_time": 41400,
        "end_time": 43200,
        "duration_on": 1800,
        "zone_number": "Zone-8",
        "group_select": ["Group-A"],
        "zone_category": "Irrigation",
        "output_type": "output-irrigation",
    }
    base.update(overrides)
    return ScheduleEntry(**base)


def make_controller(**overrides) -> ControllerTarget:
    base = {
        "name": "Controller_1",
        "name_link": "242606363309393",
        "enabled": True,
        "group_select": ["Group-A"],
        "ip_address": "192.168.1.170",
    }
    base.update(overrides)
    return ControllerTarget(**base)


def allow_irrigation(_: datetime) -> IrrigationDecision:
    return IrrigationDecision(allow=True, reason="ok")


def deny_irrigation(_: datetime) -> IrrigationDecision:
    return IrrigationDecision(allow=False, reason="rain")


def test_matches_normal_irrigation_window() -> None:
    evaluator = ScheduleEvaluator(SchedulerConfig())
    now = datetime(2026, 6, 20, 11, 45, 0)

    commands = evaluator.evaluate(
        now=now,
        schedules=[make_schedule()],
        controllers=[make_controller()],
        sun_times=SunTimes(sunrise_seconds=21600, sunset_seconds=72000),
        irrigation_policy=allow_irrigation,
    )

    assert len(commands) == 1
    assert commands[0].output_index == 7
    assert commands[0].timer_ms == 900_000


def test_suppresses_irrigation_when_policy_denies() -> None:
    evaluator = ScheduleEvaluator(SchedulerConfig())
    now = datetime(2026, 6, 20, 11, 45, 0)

    commands = evaluator.evaluate(
        now=now,
        schedules=[make_schedule()],
        controllers=[make_controller()],
        sun_times=SunTimes(sunrise_seconds=21600, sunset_seconds=72000),
        irrigation_policy=deny_irrigation,
    )

    assert commands == []


def test_cross_midnight_window_is_supported() -> None:
    evaluator = ScheduleEvaluator(SchedulerConfig())
    now = datetime(2026, 6, 20, 0, 30, 0)

    commands = evaluator.evaluate(
        now=now,
        schedules=[
            make_schedule(
                start_time=23 * 3600,
                end_time=1 * 3600,
                output_type="output-general",
            )
        ],
        controllers=[make_controller()],
        sun_times=SunTimes(sunrise_seconds=21600, sunset_seconds=72000),
        irrigation_policy=allow_irrigation,
    )

    assert len(commands) == 1
    assert commands[0].timer_ms == 1_800_000


def test_sunrise_duration_window_is_supported() -> None:
    evaluator = ScheduleEvaluator(SchedulerConfig(use_duration_sunrise=True))
    now = datetime(2026, 6, 20, 6, 10, 0)

    commands = evaluator.evaluate(
        now=now,
        schedules=[
            make_schedule(
                zone_category="Sunrise",
                start_time=None,
                end_time=None,
                duration_on=1800,
                output_type="output-general",
            )
        ],
        controllers=[make_controller()],
        sun_times=SunTimes(sunrise_seconds=6 * 3600, sunset_seconds=20 * 3600),
        irrigation_policy=allow_irrigation,
    )

    assert len(commands) == 1
    assert commands[0].timer_ms == 1_200_000
