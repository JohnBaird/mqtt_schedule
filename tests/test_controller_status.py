import json
from datetime import datetime, timedelta
from pathlib import Path

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
