from datetime import datetime

from mqtt_schedule.app import FilteredControllerRepository
from pathlib import Path

from mqtt_schedule.cli import build_weather_refresh_jobs, resolve_allowed_destinations
from mqtt_schedule.domain import ControllerTarget, IrrigationDecision, ScheduleEntry, SunTimes
from mqtt_schedule.settings import RuntimeSettings
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


def test_cli_destinations_only_narrow_configured_destinations() -> None:
    allowed = resolve_allowed_destinations(
        configured_destinations=("222", "333"),
        cli_destinations=["222", "999"],
    )

    assert allowed == {"222"}


def test_configured_destinations_apply_without_cli_override() -> None:
    allowed = resolve_allowed_destinations(
        configured_destinations=("222", "333"),
        cli_destinations=[],
    )

    assert allowed == {"222", "333"}


def test_build_weather_refresh_jobs_uses_runtime_settings(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        openweather_api_key="ow-key",
        openweather_lat=33.3,
        openweather_lon=-84.4,
        tempest_token="tempest-token",
        weather_refresh_openweather_seconds=300,
        weather_refresh_tempest_seconds=600,
        weather_refresh_run_immediately=True,
    )

    jobs = build_weather_refresh_jobs(settings=settings)

    assert [job.job_id for job in jobs] == ["openweather-refresh", "tempest-refresh"]
    assert [job.interval_seconds for job in jobs] == [300, 600]
    assert all(job.run_immediately for job in jobs)
