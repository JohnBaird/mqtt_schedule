from pathlib import Path

from mqtt_schedule.settings import RuntimeSettings


def test_runtime_settings_reads_example_json() -> None:
    settings = RuntimeSettings.from_json_file(
        Path(__file__).resolve().parent.parent / "deploy" / "runtime.example.json"
    )

    assert settings.schedule_file.as_posix() == "/etc/mqtt_schedule/airtable_schedule_data.json"
    assert settings.controller_file.as_posix() == "/etc/mqtt_schedule/airtable_config_data.json"
    assert settings.access_users_file.as_posix() == "/etc/mqtt_schedule/airtable_access_users.json"
    assert settings.clients_sysinfo_dir.as_posix() == "/etc/mqtt_schedule/clients_sysinfo"
    assert settings.transaction_csv_file.as_posix() == "/var/lib/mqtt_schedule/transactions.csv"
    assert settings.temperature_csv_file.as_posix() == "/var/lib/mqtt_schedule/temperature.csv"
    assert settings.csv_backup_dir.as_posix() == "/var/lib/mqtt_schedule/csv_backup"
    assert settings.openweather_current_file.as_posix() == "/etc/mqtt_schedule/ow_records_current.json"
    assert settings.tempest_data_dir.as_posix() == "/etc/mqtt_schedule/tempest_weather_data"
    assert settings.device_serial_file.as_posix() == "/var/lib/mqtt_schedule/device_serial.txt"
    assert settings.controller_status_file.as_posix() == "/var/lib/mqtt_schedule/controller_status.json"
    assert settings.airtable_base_url == "https://api.airtable.com/v0"
    assert settings.airtable_base_id == "appUSmE6ODKXkqLh3"
    assert settings.airtable_controller_table == "irrigation-config"
    assert settings.airtable_schedule_table == "irrigation-schedule"
    assert settings.airtable_access_users_table == "access-users"
    assert settings.commissioning_only_destinations == ()
    assert settings.mqtt_host == "localhost"
    assert settings.mqtt_port == 1883
    assert settings.access_groups == ("group1", "group2")
    assert settings.mqtt_online_status_request_enabled is True
    assert settings.mqtt_input_status_request_enabled is True
    assert settings.mqtt_temperature_request_enabled is True
    assert settings.mqtt_temperature_request_seconds == 1200
    assert settings.transaction_csv_max_entries == 5000
    assert settings.transaction_csv_backup_count == 10
    assert settings.temperature_csv_max_entries == 5000
    assert settings.temperature_csv_backup_count == 10


def test_runtime_settings_reads_commissioning_destinations_from_json(tmp_path: Path) -> None:
    config_file = tmp_path / "runtime.json"
    config_file.write_text(
        """
{
  "schedule_file": "/etc/mqtt_schedule/airtable_schedule_data.json",
  "controller_file": "/etc/mqtt_schedule/airtable_config_data.json",
  "openweather_current_file": "/etc/mqtt_schedule/ow_records_current.json",
  "openweather_forecast_file": "/etc/mqtt_schedule/ow_records_forecast.json",
  "tempest_data_dir": "/etc/mqtt_schedule/tempest_weather_data",
  "commissioning_only_destinations": ["242606363309393", "115445361687700"]
}
""".strip(),
        encoding="utf-8",
    )

    settings = RuntimeSettings.from_json_file(config_file)

    assert settings.commissioning_only_destinations == (
        "242606363309393",
        "115445361687700",
    )


def test_runtime_settings_reads_commissioning_destinations_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MQTT_SCHEDULE_ONLY_DESTINATIONS", "242606363309393, 115445361687700")
    settings = RuntimeSettings.from_env()
    assert settings.commissioning_only_destinations == (
        "242606363309393",
        "115445361687700",
    )


def test_runtime_settings_applies_env_overrides_on_top_of_json(tmp_path: Path, monkeypatch) -> None:
    config_file = tmp_path / "runtime.json"
    config_file.write_text(
        """
{
  "schedule_file": "/etc/mqtt_schedule/airtable_schedule_data.json",
  "controller_file": "/etc/mqtt_schedule/airtable_config_data.json",
  "openweather_current_file": "/etc/mqtt_schedule/ow_records_current.json",
  "openweather_forecast_file": "/etc/mqtt_schedule/ow_records_forecast.json",
  "tempest_data_dir": "/etc/mqtt_schedule/tempest_weather_data",
  "openweather_lat": 33.1,
  "openweather_lon": -84.1,
  "weather_refresh_openweather_seconds": 10800,
  "weather_refresh_tempest_seconds": 3600
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MQTT_SCHEDULE_OPENWEATHER_API_KEY", "env-openweather-key")
    monkeypatch.setenv("MQTT_SCHEDULE_TEMPEST_TOKEN", "env-tempest-token")
    monkeypatch.setenv("MQTT_SCHEDULE_OPENWEATHER_REFRESH_SECONDS", "300")
    monkeypatch.setenv("MQTT_SCHEDULE_TEMPEST_REFRESH_SECONDS", "600")
    monkeypatch.setenv("MQTT_SCHEDULE_WEATHER_REFRESH_RUN_IMMEDIATELY", "true")

    settings = RuntimeSettings.from_json_file(config_file)

    assert settings.openweather_api_key == "env-openweather-key"
    assert settings.tempest_token == "env-tempest-token"
    assert settings.weather_refresh_openweather_seconds == 300
    assert settings.weather_refresh_tempest_seconds == 600
    assert settings.weather_refresh_run_immediately is True
