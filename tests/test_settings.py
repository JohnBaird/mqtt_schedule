from pathlib import Path

from mqtt_schedule.settings import RuntimeSettings


def test_runtime_settings_reads_example_json() -> None:
    settings = RuntimeSettings.from_json_file(
        Path(__file__).resolve().parent.parent / "deploy" / "runtime.example.json"
    )

    assert settings.schedule_file.as_posix() == "/etc/mqtt_schedule/airtable_schedule_data.json"
    assert settings.controller_file.as_posix() == "/etc/mqtt_schedule/airtable_config_data.json"
    assert settings.openweather_current_file.as_posix() == "/etc/mqtt_schedule/ow_records_current.json"
    assert settings.tempest_data_dir.as_posix() == "/etc/mqtt_schedule/tempest_weather_data"
    assert settings.device_serial_file.as_posix() == "/var/lib/mqtt_schedule/device_serial.txt"
    assert settings.mqtt_host == "localhost"
    assert settings.mqtt_port == 1883
