from datetime import datetime

from mqtt_schedule.domain import ControllerTarget, IrrigationDecision, ScheduleEntry, SunTimes
from mqtt_schedule.scheduler import ScheduleEvaluator, SchedulerConfig


def test_evaluate_with_explanations_reports_matching_record() -> None:
    evaluator = ScheduleEvaluator(SchedulerConfig())
    results = evaluator.evaluate_with_explanations(
        now=datetime(2026, 6, 20, 11, 45, 0),
        schedules=[
            ScheduleEntry(
                record_id="rec-1",
                enabled=True,
                season_names=["All_seasons"],
                day_of_week=["Every_day"],
                start_time=41400,
                end_time=43200,
                duration_on=1800,
                zone_number="Zone-8",
                group_select=["Group-A"],
                zone_category="Irrigation",
                output_type="output-irrigation",
            )
        ],
        controllers=[
            ControllerTarget(
                name="Controller_1",
                name_link="242606363309393",
                enabled=True,
                group_select=["Group-A"],
                ip_address="192.168.1.170",
            )
        ],
        sun_times=SunTimes(sunrise_seconds=21600, sunset_seconds=72000),
        irrigation_policy=lambda _: IrrigationDecision(allow=True, reason="OK"),
    )

    assert len(results) == 1
    assert results[0].explanation.matched is True
    assert results[0].explanation.schedule_record_id == "rec-1"
    assert results[0].explanation.controller_links == ["242606363309393"]
    assert results[0].explanation.timer_ms == 900000
