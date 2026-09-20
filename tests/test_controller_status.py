import json
from datetime import datetime, timedelta
from pathlib import Path

from mqtt_schedule.airtable_repositories import FileControllerRepository
from mqtt_schedule.cli import build_controller_status_jobs
from mqtt_schedule.controller_status import ControllerStatusStore, ControllerStatusUpdate
from mqtt_schedule.csv_reporting import LegacyCsvRecorder
from mqtt_schedule.settings import RuntimeSettings


def test_controller_status_refresh_marks_stale_controller_offline(tmp_path: Path) -> None:
    status_file = tmp_path / "controller_status.json"
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        controller_status_file=status_file,
        controller_status_csv_file=tmp_path / "controller_status_events.csv",
        transaction_csv_file=tmp_path / "transactions.csv",
        temperature_csv_file=tmp_path / "temperature.csv",
        csv_backup_dir=tmp_path / "csv_backup",
    )
    store = ControllerStatusStore(
        status_file,
        csv_recorder=LegacyCsvRecorder.from_settings(settings),
    )
    seen_at = datetime(2026, 6, 22, 16, 7, 16)

    store.record_online_status(
        ControllerStatusUpdate(
            source_serial="242606363309393",
            response="online",
            reason="requested",
            seen_at=seen_at,
        )
    )

    store.refresh_online_flags(
        now=seen_at + timedelta(seconds=181),
        offline_after_seconds=180,
        online_recovery_after_seconds=120,
    )

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    controller = payload["controllers"]["242606363309393"]
    assert controller["online"] is False
    assert controller["last_seen_at"] == seen_at.isoformat()
    assert controller["last_offline_at"] == (seen_at + timedelta(seconds=181)).isoformat()
    csv_lines = settings.controller_status_csv_file.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == "serialSource,eventType,lastSeenAt,detectedAt,lastResponse,lastReason,thresholdSeconds"
    assert csv_lines[1] == (
        "242606363309393,offline_timeout,2026-06-22T16:07:16,2026-06-22T16:10:17,online,requested,180"
    )


def test_controller_status_refresh_keeps_fresh_controller_online(tmp_path: Path) -> None:
    status_file = tmp_path / "controller_status.json"
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        controller_status_file=status_file,
        controller_status_csv_file=tmp_path / "controller_status_events.csv",
        transaction_csv_file=tmp_path / "transactions.csv",
        temperature_csv_file=tmp_path / "temperature.csv",
        csv_backup_dir=tmp_path / "csv_backup",
    )
    store = ControllerStatusStore(
        status_file,
        csv_recorder=LegacyCsvRecorder.from_settings(settings),
    )
    seen_at = datetime(2026, 6, 22, 16, 7, 16)

    store.record_online_status(
        ControllerStatusUpdate(
            source_serial="242606363309393",
            response="online",
            reason="requested",
            seen_at=seen_at,
        )
    )

    store.refresh_online_flags(
        now=seen_at + timedelta(seconds=120),
        offline_after_seconds=180,
        online_recovery_after_seconds=120,
    )

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    controller = payload["controllers"]["242606363309393"]
    assert controller["online"] is True
    assert "last_offline_at" not in controller
    csv_lines = settings.controller_status_csv_file.read_text(encoding="utf-8").splitlines()
    assert csv_lines == [
        "serialSource,eventType,lastSeenAt,detectedAt,lastResponse,lastReason,thresholdSeconds"
    ]


def test_controller_status_recovery_requires_stable_online_window(tmp_path: Path) -> None:
    status_file = tmp_path / "controller_status.json"
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        controller_status_file=status_file,
        controller_status_csv_file=tmp_path / "controller_status_events.csv",
        transaction_csv_file=tmp_path / "transactions.csv",
        temperature_csv_file=tmp_path / "temperature.csv",
        csv_backup_dir=tmp_path / "csv_backup",
    )
    store = ControllerStatusStore(
        status_file,
        csv_recorder=LegacyCsvRecorder.from_settings(settings),
    )
    first_seen_at = datetime(2026, 6, 22, 16, 7, 16)

    store.record_online_status(
        ControllerStatusUpdate(
            source_serial="242606363309393",
            response="online",
            reason="requested",
            seen_at=first_seen_at,
        )
    )
    store.refresh_online_flags(
        now=first_seen_at + timedelta(seconds=181),
        offline_after_seconds=180,
        online_recovery_after_seconds=120,
    )

    recovery_seen_at = first_seen_at + timedelta(seconds=190)
    store.record_online_status(
        ControllerStatusUpdate(
            source_serial="242606363309393",
            response="online",
            reason="requested",
            seen_at=recovery_seen_at,
        )
    )
    store.refresh_online_flags(
        now=recovery_seen_at + timedelta(seconds=60),
        offline_after_seconds=180,
        online_recovery_after_seconds=120,
    )

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    controller = payload["controllers"]["242606363309393"]
    assert controller["online"] is False
    assert controller["recovery_started_at"] == recovery_seen_at.isoformat()

    store.refresh_online_flags(
        now=recovery_seen_at + timedelta(seconds=121),
        offline_after_seconds=180,
        online_recovery_after_seconds=120,
    )

    payload = json.loads(status_file.read_text(encoding="utf-8"))
    controller = payload["controllers"]["242606363309393"]
    assert controller["online"] is True
    assert controller["last_online_recovered_at"] == (recovery_seen_at + timedelta(seconds=121)).isoformat()
    assert "recovery_started_at" not in controller
    csv_lines = settings.controller_status_csv_file.read_text(encoding="utf-8").splitlines()
    assert csv_lines[1] == (
        "242606363309393,offline_timeout,2026-06-22T16:07:16,2026-06-22T16:10:17,online,requested,180"
    )
    assert csv_lines[2] == (
        "242606363309393,online_recovered,2026-06-22T16:10:26,2026-06-22T16:12:27,online,requested,120"
    )


def test_status_refresh_removes_saved_disabled_controller(tmp_path: Path) -> None:
    status_file = tmp_path / "controller_status.json"
    store = ControllerStatusStore(status_file)
    seen_at = datetime(2026, 9, 19, 16, 28, 34)
    store.record_online_status(ControllerStatusUpdate(
        source_serial="167227924461412",
        response="online",
        reason="requested",
        seen_at=seen_at,
    ))

    store.refresh_online_flags(
        now=seen_at + timedelta(seconds=200),
        enabled_serials=set(),
        offline_after_seconds=180,
        online_recovery_after_seconds=120,
    )

    controllers = json.loads(status_file.read_text(encoding="utf-8"))["controllers"]
    assert "167227924461412" not in controllers


def test_status_job_tracks_only_enabled_airtable_controllers(tmp_path: Path) -> None:
    controller_file = tmp_path / "airtable_config_data.json"
    controller_file.write_text(json.dumps({"records": [
        {"id": "rec-1", "fields": {"Name": "Enabled", "nameLink": "111", "enabled": True}},
        {"id": "rec-2", "fields": {"Name": "Disabled", "nameLink": "222", "enabled": False}},
    ]}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "schedules.json",
        controller_file=controller_file,
        access_users_file=tmp_path / "users.json",
        clients_sysinfo_dir=tmp_path / "sysinfo",
        openweather_current_file=tmp_path / "weather.json",
        openweather_forecast_file=tmp_path / "forecast.json",
        tempest_data_dir=tmp_path / "tempest",
        device_serial_file=tmp_path / "serial.txt",
        controller_status_file=tmp_path / "controller_status.json",
    )
    store = ControllerStatusStore(settings.controller_status_file)
    store.record_online_status(ControllerStatusUpdate(
        source_serial="222",
        response="online",
        reason="requested",
        seen_at=datetime(2026, 9, 19, 16, 28, 34),
    ))

    job = build_controller_status_jobs(
        settings=settings,
        controller_status_store=store,
        controller_repository=FileControllerRepository(controller_file),
    )[0]
    job.fn()

    controllers = json.loads(settings.controller_status_file.read_text(encoding="utf-8"))["controllers"]
    assert set(controllers) == {"111"}
    assert controllers["111"]["online"] is False


def test_status_refresh_reports_enabled_controller_that_never_replied(tmp_path: Path) -> None:
    status_file = tmp_path / "controller_status.json"
    settings = RuntimeSettings(
        schedule_file=tmp_path / "schedules.json",
        controller_file=tmp_path / "controllers.json",
        access_users_file=tmp_path / "users.json",
        clients_sysinfo_dir=tmp_path / "sysinfo",
        openweather_current_file=tmp_path / "weather.json",
        openweather_forecast_file=tmp_path / "forecast.json",
        tempest_data_dir=tmp_path / "tempest",
        device_serial_file=tmp_path / "serial.txt",
        controller_status_file=status_file,
        controller_status_csv_file=tmp_path / "events.csv",
        transaction_csv_file=tmp_path / "transactions.csv",
        temperature_csv_file=tmp_path / "temperature.csv",
        csv_backup_dir=tmp_path / "backups",
    )
    store = ControllerStatusStore(status_file, csv_recorder=LegacyCsvRecorder.from_settings(settings))
    start = datetime(2026, 9, 19, 16, 0, 0)
    kwargs = dict(enabled_serials={"242606363309393"}, offline_after_seconds=180, online_recovery_after_seconds=120)
    store.refresh_online_flags(now=start, **kwargs)
    store.refresh_online_flags(now=start + timedelta(seconds=181), **kwargs)
    store.refresh_online_flags(now=start + timedelta(seconds=241), **kwargs)

    controller = json.loads(status_file.read_text(encoding="utf-8"))["controllers"]["242606363309393"]
    assert controller["online"] is False
    assert controller["last_offline_at"] == (start + timedelta(seconds=181)).isoformat()
    lines = settings.controller_status_csv_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[1].split(",")[1] == "offline_timeout"


def test_reenabled_controller_without_reply_starts_new_timeout(tmp_path: Path) -> None:
    status_file = tmp_path / "controller_status.json"
    store = ControllerStatusStore(status_file)
    serial = "242606363309393"
    start = datetime(2026, 9, 19, 16, 0, 0)
    timeout = dict(offline_after_seconds=180, online_recovery_after_seconds=120)

    store.refresh_online_flags(now=start, enabled_serials={serial}, **timeout)
    store.refresh_online_flags(now=start + timedelta(seconds=60), enabled_serials=set(), **timeout)
    restarted_at = start + timedelta(seconds=600)
    store.refresh_online_flags(now=restarted_at, enabled_serials={serial}, **timeout)
    store.refresh_online_flags(now=restarted_at + timedelta(seconds=181), enabled_serials={serial}, **timeout)

    controller = json.loads(status_file.read_text(encoding="utf-8"))["controllers"][serial]
    assert controller["monitoring_started_at"] == restarted_at.isoformat()
    assert controller["last_offline_at"] == (restarted_at + timedelta(seconds=181)).isoformat()
