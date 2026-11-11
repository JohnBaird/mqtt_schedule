import json
from pathlib import Path

import pytest

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
    assert settings.controller_offline_after_seconds == 180
    assert settings.controller_online_recovery_after_seconds == 120
    assert settings.controller_status_csv_file.as_posix() == "/var/lib/mqtt_schedule/controller_status_events.csv"
    assert settings.airtable_base_url == "https://api.airtable.com/v0"
    assert settings.airtable_base_id == "appUSmE6ODKXkqLh3"
    assert settings.airtable_controller_table == "irrigation-config"
    assert settings.airtable_schedule_table == "irrigation-schedule"
    assert settings.airtable_access_users_table == "access-users"
    assert settings.airtable_sync_seconds == 86400
    assert settings.airtable_controller_sync_run_immediately is False
    assert settings.airtable_schedule_sync_run_immediately is False
    assert settings.airtable_access_users_sync_run_immediately is False
    assert settings.input_alerts_file.as_posix() == "/etc/mqtt_schedule/airtable_input_alerts.json"
    assert settings.airtable_input_alerts_table == "input-alerts"
    assert settings.airtable_input_alerts_sync_enabled is False
    assert settings.airtable_input_alerts_sync_run_immediately is False
    assert settings.sms_enabled is False
    assert settings.sms_service_start_enabled is True
    assert settings.email_enabled is False
    assert settings.email_service_start_enabled is True
    assert settings.email_smtp_host == "smtp.gmail.com"
    assert settings.email_smtp_port == 587
    assert settings.email_smtp_timeout_seconds == 10
    assert settings.mongo_db == "homeWeather"
    assert settings.mongo_col_stations == "stations"
    assert settings.mongo_col_open_weather == "open_weather"
    assert settings.mongo_col_tempest_flow == "tempest_flow"
    assert settings.mongo_col_ingestion_runs == "ingestion_runs"
    assert settings.mongo_connect_timeout_ms == 3000
    assert settings.mongo_server_selection_timeout_ms == 3000
    assert settings.mongo_openweather_ingest_seconds == 10800
    assert settings.mongo_openweather_ingest_run_immediately is False
    assert settings.mongo_tempest_ingest_seconds == 3600
    assert settings.mongo_tempest_ingest_run_immediately is False
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
    assert settings.controller_status_csv_max_entries == 5000
    assert settings.controller_status_csv_backup_count == 10


def test_runtime_settings_rejects_legacy_controller_list(tmp_path: Path) -> None:
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy" / "runtime.example.json").read_text(encoding="utf-8"))
    config["commissioning_only_destinations"] = {"Controller_1": {"serial": "242606363309393", "enabled": True}}
    config_file = tmp_path / "runtime.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="Remove commissioning_only_destinations"):
        RuntimeSettings.from_json_file(config_file)



def test_airtable_startup_flags_require_json_booleans(tmp_path: Path) -> None:
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy" / "runtime.example.json").read_text(encoding="utf-8"))
    config["airtable_controller_sync_run_immediately"] = "false"
    config_file = tmp_path / "runtime.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="airtable_controller_sync_run_immediately must be a JSON boolean"):
        RuntimeSettings.from_json_file(config_file)


def test_legacy_airtable_startup_flag_is_ignored(tmp_path: Path, caplog) -> None:
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy" / "runtime.example.json").read_text(encoding="utf-8"))
    config["airtable_sync_run_immediately"] = True
    config_file = tmp_path / "runtime.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")

    settings = RuntimeSettings.from_json_file(config_file)

    assert settings.airtable_controller_sync_run_immediately is False
    assert settings.airtable_schedule_sync_run_immediately is False
    assert settings.airtable_access_users_sync_run_immediately is False
    assert "airtable_sync_run_immediately is ignored" in caplog.text

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
  "airtable_sync_seconds": 900,
  "mongo_db": "homeWeather",
  "weather_refresh_openweather_seconds": 10800,
  "weather_refresh_tempest_seconds": 3600
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MQTT_SCHEDULE_OPENWEATHER_API_KEY", "env-openweather-key")
    monkeypatch.setenv("MQTT_SCHEDULE_TEMPEST_TOKEN", "env-tempest-token")
    monkeypatch.setenv("MQTT_SCHEDULE_AIRTABLE_SYNC_SECONDS", "300")
    monkeypatch.setenv("MQTT_SCHEDULE_AIRTABLE_CONTROLLER_SYNC_RUN_IMMEDIATELY", "true")
    monkeypatch.setenv("MQTT_SCHEDULE_AIRTABLE_ACCESS_USERS_SYNC_RUN_IMMEDIATELY", "true")
    monkeypatch.setenv("MQTT_SCHEDULE_MONGO_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("MQTT_SCHEDULE_MONGO_AUTHENTICATE", "true")
    monkeypatch.setenv("MQTT_SCHEDULE_MONGO_USERNAME", "dbuser")
    monkeypatch.setenv("MQTT_SCHEDULE_MONGO_PASSWORD", "dbpass")
    monkeypatch.setenv("MQTT_SCHEDULE_MONGO_OPENWEATHER_INGEST_SECONDS", "1800")
    monkeypatch.setenv("MQTT_SCHEDULE_MONGO_OPENWEATHER_INGEST_RUN_IMMEDIATELY", "true")
    monkeypatch.setenv("MQTT_SCHEDULE_MONGO_TEMPEST_INGEST_SECONDS", "600")
    monkeypatch.setenv("MQTT_SCHEDULE_MONGO_TEMPEST_INGEST_RUN_IMMEDIATELY", "true")
    monkeypatch.setenv("MQTT_SCHEDULE_OPENWEATHER_REFRESH_SECONDS", "300")
    monkeypatch.setenv("MQTT_SCHEDULE_TEMPEST_REFRESH_SECONDS", "600")
    monkeypatch.setenv("MQTT_SCHEDULE_WEATHER_REFRESH_RUN_IMMEDIATELY", "true")

    settings = RuntimeSettings.from_json_file(config_file)

    assert settings.openweather_api_key == "env-openweather-key"
    assert settings.tempest_token == "env-tempest-token"
    assert settings.airtable_sync_seconds == 300
    assert settings.airtable_controller_sync_run_immediately is True
    assert settings.airtable_schedule_sync_run_immediately is False
    assert settings.airtable_access_users_sync_run_immediately is True
    assert settings.mongo_uri == "mongodb://127.0.0.1:27017"
    assert settings.mongo_db == "homeWeather"
    assert settings.mongo_authenticate is True
    assert settings.mongo_username == "dbuser"
    assert settings.mongo_password == "dbpass"
    assert settings.mongo_openweather_ingest_seconds == 1800
    assert settings.mongo_openweather_ingest_run_immediately is True
    assert settings.mongo_tempest_ingest_seconds == 600
    assert settings.mongo_tempest_ingest_run_immediately is True
    assert settings.weather_refresh_openweather_seconds == 300
    assert settings.weather_refresh_tempest_seconds == 600
    assert settings.weather_refresh_run_immediately is True


def test_runtime_settings_reads_controller_offline_timeout_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MQTT_SCHEDULE_CONTROLLER_OFFLINE_AFTER_SECONDS", "420")
    monkeypatch.setenv("MQTT_SCHEDULE_CONTROLLER_ONLINE_RECOVERY_AFTER_SECONDS", "240")

    settings = RuntimeSettings.from_env()

    assert settings.controller_offline_after_seconds == 420
    assert settings.controller_online_recovery_after_seconds == 240


def test_sms_switches_are_controlled_by_runtime_json(tmp_path: Path, monkeypatch) -> None:
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy/runtime.example.json").read_text())
    config["sms_enabled"] = True
    config["sms_service_start_enabled"] = False
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("MQTT_SCHEDULE_SMS_ENABLED", "false")
    monkeypatch.setenv("MQTT_SCHEDULE_SMS_SERVICE_START_ENABLED", "true")

    settings = RuntimeSettings.from_json_file(path)

    assert settings.sms_enabled is True
    assert settings.sms_service_start_enabled is False
    config["sms_enabled"] = False
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("MQTT_SCHEDULE_SMS_ENABLED", "true")
    assert RuntimeSettings.from_json_file(path).sms_enabled is False


@pytest.mark.parametrize("name", ["sms_enabled", "sms_service_start_enabled", "email_enabled", "email_service_start_enabled",
                                 "airtable_input_alerts_sync_enabled", "airtable_input_alerts_sync_run_immediately",
                                 "input_alerts_enabled", "daily_log_report_enabled", "daily_log_report_run_immediately"])
@pytest.mark.parametrize("value", ["false", 0, None])
def test_sms_switches_require_json_booleans(tmp_path: Path, name, value) -> None:
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy/runtime.example.json").read_text())
    config[name] = value
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match=f"{name} must be a JSON boolean"):
        RuntimeSettings.from_json_file(path)


def test_twilio_values_are_environment_only_and_hidden_from_repr(tmp_path: Path, monkeypatch) -> None:
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy/runtime.example.json").read_text())
    config.update({
        "twilio_account_sid": "ignored-json-account",
        "twilio_auth_token": "ignored-json-token",
        "twilio_from_number": "+15550009999",
        "twilio_to_numbers": ["+15550008888"],
    })
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    variables = {
        "MQTT_SCHEDULE_TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
        "MQTT_SCHEDULE_TWILIO_AUTH_TOKEN": "test-only-private-token",
        "MQTT_SCHEDULE_TWILIO_FROM_NUMBER": "+15550001111",
        "MQTT_SCHEDULE_TWILIO_TO_NUMBERS": "+15550002222, +15550003333",
    }
    for name in variables:
        monkeypatch.delenv(name, raising=False)
    settings = RuntimeSettings.from_json_file(path)
    assert settings.twilio_account_sid is None
    assert settings.twilio_auth_token is None
    assert settings.twilio_from_number is None
    assert settings.twilio_to_numbers == ()

    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    settings = RuntimeSettings.from_json_file(path)
    assert settings.twilio_account_sid == variables["MQTT_SCHEDULE_TWILIO_ACCOUNT_SID"]
    assert settings.twilio_auth_token == variables["MQTT_SCHEDULE_TWILIO_AUTH_TOKEN"]
    assert settings.twilio_from_number == "+15550001111"
    assert settings.twilio_to_numbers == ("+15550002222", "+15550003333")
    assert "test-only-private-token" not in repr(settings)
    assert "+15550001111" not in repr(settings)
    assert "+15550002222" not in repr(settings)
    assert RuntimeSettings.from_env().twilio_auth_token == "test-only-private-token"
    assert RuntimeSettings.from_env().sms_enabled is False


def test_email_switches_and_smtp_settings_are_controlled_by_runtime_json(tmp_path: Path, monkeypatch) -> None:
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy/runtime.example.json").read_text())
    config.update({"email_enabled": True, "email_service_start_enabled": False,
                   "email_smtp_host": "smtp.example.test", "email_smtp_port": 2525,
                   "email_smtp_timeout_seconds": 15})
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("MQTT_SCHEDULE_EMAIL_ENABLED", "false")
    monkeypatch.setenv("MQTT_SCHEDULE_EMAIL_SERVICE_START_ENABLED", "true")
    settings = RuntimeSettings.from_json_file(path)
    assert settings.email_enabled is True
    assert settings.email_service_start_enabled is False
    assert settings.email_smtp_host == "smtp.example.test"
    assert settings.email_smtp_port == 2525
    assert settings.email_smtp_timeout_seconds == 15
    config["email_enabled"] = False
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("MQTT_SCHEDULE_EMAIL_ENABLED", "true")
    assert RuntimeSettings.from_json_file(path).email_enabled is False


def test_email_credentials_are_environment_only_and_not_in_repr(tmp_path: Path, monkeypatch) -> None:
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy/runtime.example.json").read_text())
    config.update({"sender_email_address": "ignored@example.test", "email_password": "ignored-json-password",
                   "receiver_email_addresses": ["ignored@example.test"]})
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    variables = {
        "MQTT_SCHEDULE_SENDER_EMAIL_ADDRESS": "sender@example.test",
        "MQTT_SCHEDULE_EMAIL_PASSWORD": "test-private-email-password",
        "MQTT_SCHEDULE_RECEIVER_EMAIL_ADDRESS_1": " first@example.test ",
        "MQTT_SCHEDULE_RECEIVER_EMAIL_ADDRESS_2": "second@example.test",
    }
    for name in variables:
        monkeypatch.delenv(name, raising=False)
    settings = RuntimeSettings.from_json_file(path)
    assert settings.sender_email_address is None
    assert settings.email_password is None
    assert settings.receiver_email_addresses == ()
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    settings = RuntimeSettings.from_json_file(path)
    assert settings.sender_email_address == "sender@example.test"
    assert settings.email_password == "test-private-email-password"
    assert settings.receiver_email_addresses == ("first@example.test", "second@example.test")
    assert "test-private-email-password" not in repr(settings)
    assert "sender@example.test" not in repr(settings)
    assert "first@example.test" not in repr(settings)
    assert RuntimeSettings.from_env().email_password == "test-private-email-password"
    assert RuntimeSettings.from_env().email_enabled is False
    monkeypatch.setenv("MQTT_SCHEDULE_RECEIVER_EMAIL_ADDRESS_1", "")
    assert RuntimeSettings.from_json_file(path).receiver_email_addresses == ("second@example.test",)


def test_input_alert_execution_controls_are_json_only_and_state_path_has_env_override(tmp_path, monkeypatch):
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy/runtime.example.json").read_text())
    assert config["input_alerts_enabled"] is False
    config.update(input_alerts_enabled=True, input_alerts_max_age_seconds=120,
                  input_alert_state_file=str(tmp_path / "configured-state.json"))
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("MQTT_SCHEDULE_INPUT_ALERTS_ENABLED", "false")
    monkeypatch.setenv("MQTT_SCHEDULE_INPUT_ALERTS_MAX_AGE_SECONDS", "999")
    settings = RuntimeSettings.from_json_file(path)
    assert settings.input_alerts_enabled is True
    assert settings.input_alerts_max_age_seconds == 120
    assert settings.input_alert_state_file == tmp_path / "configured-state.json"
    monkeypatch.setenv("MQTT_SCHEDULE_INPUT_ALERT_STATE_FILE", str(tmp_path / "override-state.json"))
    assert RuntimeSettings.from_json_file(path).input_alert_state_file == tmp_path / "override-state.json"
    monkeypatch.setenv("MQTT_SCHEDULE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("MQTT_SCHEDULE_INPUT_ALERT_STATE_FILE")
    assert RuntimeSettings.from_env().input_alert_state_file == tmp_path / "state" / "input_alert_state.json"
    assert RuntimeSettings.from_env().input_alerts_enabled is False


@pytest.mark.parametrize("age", [0, -1, True, "300", 0.5, None, 86401])
def test_input_alert_age_must_be_a_positive_bounded_integer(tmp_path, age):
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy/runtime.example.json").read_text())
    config["input_alerts_max_age_seconds"] = age
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="input_alerts_max_age_seconds"):
        RuntimeSettings.from_json_file(path)


def test_log_report_settings_are_json_controlled_and_paths_support_private_environment(tmp_path, monkeypatch):
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy/runtime.example.json").read_text())
    config.update(log_file=str(tmp_path / "logs" / "app.log"), log_backup_count=7,
                  daily_log_report_enabled=True, daily_log_report_run_immediately=False,
                  daily_log_report_time="21:00", daily_log_report_state_file=str(tmp_path / "report.json"))
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setenv("MQTT_SCHEDULE_DAILY_LOG_REPORT_ENABLED", "false")
    monkeypatch.setenv("MQTT_SCHEDULE_DAILY_LOG_REPORT_RUN_IMMEDIATELY", "true")
    value = RuntimeSettings.from_json_file(path)
    assert value.daily_log_report_enabled is True and value.daily_log_report_run_immediately is False
    assert value.log_backup_count == 7 and value.daily_log_report_time == "21:00"
    assert value.log_file == tmp_path / "logs" / "app.log"
    monkeypatch.setenv("MQTT_SCHEDULE_LOG_FILE", str(tmp_path / "override.log"))
    monkeypatch.setenv("MQTT_SCHEDULE_DAILY_LOG_REPORT_STATE_FILE", str(tmp_path / "override.json"))
    assert RuntimeSettings.from_json_file(path).log_file == tmp_path / "override.log"
    assert RuntimeSettings.from_env().daily_log_report_state_file == tmp_path / "override.json"
    assert RuntimeSettings.from_env().daily_log_report_enabled is False


@pytest.mark.parametrize("changes", [
    {"log_backup_count": 0}, {"log_backup_count": "7"}, {"log_backup_count": True},
    {"daily_log_report_time": "25:00"}, {"daily_log_report_time": "9:00"},
    {"daily_log_report_time": "21:60"}, {"daily_log_report_time": None},
])
def test_invalid_log_report_settings_are_rejected(tmp_path, changes):
    config = json.loads((Path(__file__).resolve().parent.parent / "deploy/runtime.example.json").read_text())
    config.update(changes)
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError):
        RuntimeSettings.from_json_file(path)
