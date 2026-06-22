from datetime import datetime
import json

from mqtt_schedule.app import FilteredControllerRepository
from pathlib import Path

from mqtt_schedule.cli import (
    _ensure_required_airtable_files,
    _handle_access_request,
    _sync_airtable_now,
    _validate_airtable_files,
    build_airtable_sync_jobs,
    build_mqtt_request_jobs,
    build_openweather_mongo_ingest_jobs,
    build_tempest_mongo_ingest_jobs,
    build_weather_refresh_jobs,
    resolve_allowed_destinations,
)
from mqtt_schedule.domain import ControllerTarget, IrrigationDecision, ScheduleEntry, SunTimes
from mqtt_schedule.mqtt_adapter import MQTTBrokerSettings, MQTTCommandEncoder, MQTTMaintenancePublisher, RecordingMQTTClient
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
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
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


def test_build_airtable_sync_jobs_uses_runtime_settings(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        airtable_base_id="app123",
        airtable_api_key="pat123",
        airtable_sync_seconds=300,
        airtable_sync_run_immediately=True,
    )

    jobs = build_airtable_sync_jobs(settings=settings)

    assert [job.job_id for job in jobs] == ["airtable-sync"]
    assert [job.interval_seconds for job in jobs] == [300]
    assert all(job.run_immediately for job in jobs)


def test_build_airtable_sync_jobs_returns_empty_when_not_configured(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
    )

    jobs = build_airtable_sync_jobs(settings=settings)

    assert jobs == []


def test_build_tempest_mongo_ingest_jobs_uses_runtime_settings(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        mongo_uri="mongodb://127.0.0.1:27017",
        mongo_db="homeWeather",
        mongo_tempest_ingest_seconds=300,
        mongo_tempest_ingest_run_immediately=True,
    )

    jobs = build_tempest_mongo_ingest_jobs(settings=settings)

    assert [job.job_id for job in jobs] == ["tempest-mongo-ingest"]
    assert [job.interval_seconds for job in jobs] == [300]
    assert all(job.run_immediately for job in jobs)


def test_build_openweather_mongo_ingest_jobs_uses_runtime_settings(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        mongo_uri="mongodb://127.0.0.1:27017",
        mongo_db="homeWeather",
        mongo_openweather_ingest_seconds=900,
        mongo_openweather_ingest_run_immediately=True,
    )

    jobs = build_openweather_mongo_ingest_jobs(settings=settings)

    assert [job.job_id for job in jobs] == ["openweather-mongo-ingest"]
    assert [job.interval_seconds for job in jobs] == [900]
    assert all(job.run_immediately for job in jobs)


def test_build_openweather_mongo_ingest_jobs_returns_empty_when_not_configured(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
    )

    jobs = build_openweather_mongo_ingest_jobs(settings=settings)

    assert jobs == []


def test_build_tempest_mongo_ingest_jobs_returns_empty_when_not_configured(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
    )

    jobs = build_tempest_mongo_ingest_jobs(settings=settings)

    assert jobs == []


def test_validate_airtable_files_returns_success_for_valid_exports(tmp_path: Path, capsys) -> None:
    schedule_file = tmp_path / "airtable_schedule_data.json"
    controller_file = tmp_path / "airtable_config_data.json"
    access_users_file = tmp_path / "airtable_access_users.json"
    schedule_file.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "rec-1",
                        "fields": {
                            "zoneNumber": ["Zone-8"],
                            "enabled": True,
                            "seasonNames": ["All_seasons"],
                            "day_of_week": ["Every_day"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    controller_file.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "rec-2",
                        "fields": {
                            "Name": "Controller_1",
                            "nameLink": "242606363309393",
                            "enabled": True,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    access_users_file.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "rec-3",
                        "fields": {
                            "firstName": "John",
                            "pinNumber": "12345",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = RuntimeSettings(
        schedule_file=schedule_file,
        controller_file=controller_file,
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
    )

    result = _validate_airtable_files(settings)
    output = capsys.readouterr().out

    assert result == 0
    assert "airtable_file kind=schedule" in output
    assert "airtable_file kind=controller" in output
    assert "airtable_file kind=access_users" in output


def test_validate_airtable_files_returns_failure_for_invalid_export(tmp_path: Path, capsys) -> None:
    schedule_file = tmp_path / "airtable_schedule_data.json"
    controller_file = tmp_path / "airtable_config_data.json"
    access_users_file = tmp_path / "airtable_access_users.json"
    schedule_file.write_text(json.dumps({"broken": []}), encoding="utf-8")
    controller_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    access_users_file.write_text(json.dumps({"broken": []}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=schedule_file,
        controller_file=controller_file,
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
    )

    result = _validate_airtable_files(settings)
    output = capsys.readouterr().out

    assert result == 1
    assert "airtable_issue kind=schedule severity=error" in output


def test_sync_airtable_now_prints_results(tmp_path: Path, capsys, monkeypatch) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
    )

    class FakeSyncService:
        def __init__(self, _settings):
            self.settings = _settings

        def sync_all(self):
            from mqtt_schedule.airtable_sync import AirtableSyncFileResult

            return [
                AirtableSyncFileResult(
                    file_kind="controller",
                    table_name="irrigation-config",
                    output_path=self.settings.controller_file,
                    record_count=3,
                    action="updated",
                )
            ]

    monkeypatch.setattr("mqtt_schedule.cli.AirtableSyncService", FakeSyncService)

    result = _sync_airtable_now(settings)
    output = capsys.readouterr().out

    assert result == 0
    assert "airtable_sync kind=controller" in output
    assert "action=updated" in output


def test_ensure_required_airtable_files_syncs_when_missing(tmp_path: Path, monkeypatch) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
    )

    class FakeSyncService:
        def __init__(self, _settings):
            self.settings = _settings

        def required_files_missing(self):
            return [self.settings.schedule_file, self.settings.controller_file, self.settings.access_users_file]

        def is_configured(self):
            return True

        def sync_all(self):
            for path in (
                self.settings.schedule_file,
                self.settings.controller_file,
                self.settings.access_users_file,
            ):
                path.write_text('{"records": []}', encoding="utf-8")
            return []

    monkeypatch.setattr("mqtt_schedule.cli.AirtableSyncService", FakeSyncService)

    _ensure_required_airtable_files(settings)

    assert settings.schedule_file.exists()
    assert settings.controller_file.exists()
    assert settings.access_users_file.exists()


def test_build_mqtt_request_jobs_uses_filtered_enabled_controllers(tmp_path: Path) -> None:
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        mqtt_online_status_request_enabled=True,
        mqtt_input_status_request_enabled=True,
        mqtt_temperature_request_enabled=True,
        mqtt_online_status_request_seconds=60,
        mqtt_input_status_request_seconds=60,
        mqtt_temperature_request_seconds=1200,
    )
    repo = FilteredControllerRepository(
        base=StaticControllerRepository(
            [
                ControllerTarget("A", "111", True, ["Group-A"]),
                ControllerTarget("B", "222", False, ["Group-A"]),
                ControllerTarget("C", "333", True, ["Group-A"]),
            ]
        ),
        allowed_destinations={"111"},
    )
    client = RecordingMQTTClient()
    maintenance_publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )

    jobs = build_mqtt_request_jobs(
        settings=settings,
        controller_repository=repo,
        maintenance_publisher=maintenance_publisher,
    )

    assert [job.job_id for job in jobs] == [
        "mqtt-online-status-request",
        "mqtt-input-status-request",
        "mqtt-temperature-request",
    ]

    jobs[0].fn()
    jobs[1].fn()
    jobs[2].fn()

    published_topics = [topic for topic, _ in client.published]
    assert published_topics == [
        "SPV1.0/irrigation/stc_online_status_request/281261212083555/111",
        "SPV1.0/irrigation/stc_input_status_request/281261212083555/111",
        "SPV1.0/irrigation/stc_temperature_request/281261212083555/111",
    ]


def test_handle_access_request_returns_legacy_response(tmp_path: Path, capsys) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "rec-1",
                        "fields": {
                            "firstName": "John",
                            "lastName": "Baird",
                            "enabled": "true",
                            "pinCode": "12345",
                            "pinNumber": "12345",
                            "accessGroups": ["group1", "group2"],
                            "cardNumber": "10810",
                            "faceId": "620827",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1", "group2"),
    )
    client = RecordingMQTTClient()
    maintenance_publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
                session_client_id="6410332930780559595",
                host_name="server",
                ip_address="192.168.1.53",
            )
        ),
        client=client,
    )

    result = _handle_access_request(
        settings=settings,
        maintenance_publisher=maintenance_publisher,
        topic="SPV1.0/irrigation/stc_access_request/242606363309393/281261212083555",
        payload_json=json.dumps(
            {
                "_iD": "3a32dc83322a4aae8d556ab0",
                "pinCode": None,
                "pinNumber": "12345",
                "cardNumber": None,
                "faceId": None,
            }
        ),
    )
    output = capsys.readouterr().out

    assert result == 0
    assert "access_request_result" in output
    assert "granted=True" in output
    assert client.published[0][0] == (
        "SPV1.0/irrigation/stc_access_response/281261212083555/242606363309393"
    )
    response_payload = json.loads(client.published[0][1])
    assert response_payload["granted"] is True
    assert response_payload["fullName"] == "John Baird"
    assert response_payload["pinNumber"] == "12345"
