from datetime import datetime

from mqtt_schedule.airtable_repositories import FileControllerRepository
from mqtt_schedule.cli import FilteredControllerRepository
from mqtt_schedule.domain import ControllerTarget, IrrigationDecision, ScheduleEntry, SunTimes
from mqtt_schedule.scheduler import ScheduleEvaluator, SchedulerConfig


class StaticControllerRepository:
    def __init__(self, controllers):
        self.controllers = controllers

    def list_controllers(self):
        return self.controllers


def test_filtered_controller_repository_limits_destinations() -> None:
    repo = FilteredControllerRepository(
        base=StaticControllerRepository(
            [
                ControllerTarget("A", "111", True, ["Group-A"]),
                ControllerTarget("B", "222", True, ["Group-A"]),
            ]
        ),
        allowed_destinations={"222"},
    )

    controllers = repo.list_controllers()

    assert [item.name_link for item in controllers] == ["222"]


def test_scheduler_targets_only_filtered_controller() -> None:
    evaluator = ScheduleEvaluator(SchedulerConfig())
    controllers = FilteredControllerRepository(
        base=StaticControllerRepository(
            [
                ControllerTarget("A", "111", True, ["Group-A"]),
                ControllerTarget("B", "222", True, ["Group-A"]),
            ]
        ),
        allowed_destinations={"222"},
    ).list_controllers()

    commands = evaluator.evaluate(
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
                zone_category="General",
                output_type="output-general",
            )
        ],
        controllers=controllers,
        sun_times=SunTimes(sunrise_seconds=21600, sunset_seconds=72000),
        irrigation_policy=lambda _: IrrigationDecision(allow=True, reason="OK"),
    )

    assert len(commands) == 1
    assert commands[0].controller_links == ["222"]
