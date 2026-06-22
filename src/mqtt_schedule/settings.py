from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeSettings:
    schedule_file: Path
    controller_file: Path
    access_users_file: Path
    clients_sysinfo_dir: Path
    openweather_current_file: Path
    openweather_forecast_file: Path
    tempest_data_dir: Path
    device_serial_file: Path
    controller_status_file: Path = Path("/var/lib/mqtt_schedule/controller_status.json")
    controller_offline_after_seconds: int = 3 * 60
    controller_online_recovery_after_seconds: int = 2 * 60
    controller_status_csv_file: Path = Path("/var/lib/mqtt_schedule/controller_status_events.csv")
    transaction_csv_file: Path = Path("/var/lib/mqtt_schedule/transactions.csv")
    temperature_csv_file: Path = Path("/var/lib/mqtt_schedule/temperature.csv")
    csv_backup_dir: Path = Path("/var/lib/mqtt_schedule/csv_backup")
    commissioning_only_destinations: tuple[str, ...] = ()
    source_serial_override: str | None = None
    tempest_station_id: int = 201749
    openweather_url: str = "https://api.openweathermap.org/data/2.5"
    openweather_api_key: str | None = None
    openweather_lat: float | None = None
    openweather_lon: float | None = None
    openweather_units: str = "imperial"
    airtable_base_url: str = "https://api.airtable.com/v0"
    airtable_base_id: str | None = None
    airtable_api_key: str | None = None
    airtable_controller_table: str = "irrigation-config"
    airtable_schedule_table: str = "irrigation-schedule"
    airtable_access_users_table: str = "access-users"
    tempest_base_url: str = "https://swd.weatherflow.com/swd/rest"
    tempest_token: str | None = None
    weather_refresh_openweather_seconds: int = 3 * 3600
    weather_refresh_tempest_seconds: int = 3600
    weather_refresh_run_immediately: bool = False
    tempest_snapshot_keep: int = 5
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_keepalive: int = 60
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_online_status_request_enabled: bool = True
    mqtt_input_status_request_enabled: bool = True
    mqtt_temperature_request_enabled: bool = True
    mqtt_online_status_request_seconds: int = 60
    mqtt_input_status_request_seconds: int = 60
    mqtt_temperature_request_seconds: int = 20 * 60
    mqtt_topic_version: str = "SPV1.0"
    mqtt_domain: str = "irrigation"
    timezone_name: str = "America/New_York"
    hemisphere: str = "north"
    use_duration_sunrise: bool = True
    use_duration_sunset: bool = False
    program_name: str = "mqtt_schedule"
    program_version: str = "0.1.0"
    access_groups: tuple[str, ...] = ()
    transaction_csv_max_entries: int = 5000
    transaction_csv_backup_count: int = 10
    temperature_csv_max_entries: int = 5000
    temperature_csv_backup_count: int = 10
    controller_status_csv_max_entries: int = 5000
    controller_status_csv_backup_count: int = 10
    rain_now_block_mm: float = 2.0
    rain_24h_block_mm: float = 5.0
    rain_48h_block_mm: float = 8.0
    rain_7d_block_mm: float = 15.0
    require_latest_within_minutes: int = 180

    @classmethod
    def from_env(cls) -> RuntimeSettings:
        base_dir = Path(os.environ.get("MQTT_SCHEDULE_DATA_DIR", "/etc/mqtt_schedule"))
        state_dir = Path(os.environ.get("MQTT_SCHEDULE_STATE_DIR", "/var/lib/mqtt_schedule"))
        schedule_file = Path(
            os.environ.get(
                "MQTT_SCHEDULE_SCHEDULE_FILE",
                str(base_dir / "airtable_schedule_data.json"),
            )
        )
        controller_file = Path(
            os.environ.get(
                "MQTT_SCHEDULE_CONTROLLER_FILE",
                str(base_dir / "airtable_config_data.json"),
            )
        )
        transaction_csv_file = Path(
            os.environ.get(
                "MQTT_SCHEDULE_TRANSACTION_CSV_FILE",
                str(state_dir / "transactions.csv"),
            )
        )
        temperature_csv_file = Path(
            os.environ.get(
                "MQTT_SCHEDULE_TEMPERATURE_CSV_FILE",
                str(state_dir / "temperature.csv"),
            )
        )
        controller_status_csv_file = Path(
            os.environ.get(
                "MQTT_SCHEDULE_CONTROLLER_STATUS_CSV_FILE",
                str(state_dir / "controller_status_events.csv"),
            )
        )
        csv_backup_dir = Path(
            os.environ.get(
                "MQTT_SCHEDULE_CSV_BACKUP_DIR",
                str(state_dir / "csv_backup"),
            )
        )
        controller_status_file = Path(
            os.environ.get(
                "MQTT_SCHEDULE_CONTROLLER_STATUS_FILE",
                str(state_dir / "controller_status.json"),
            )
        )
        openweather_current_file = Path(
            os.environ.get(
                "MQTT_SCHEDULE_OPENWEATHER_CURRENT_FILE",
                str(base_dir / "ow_records_current.json"),
            )
        )
        openweather_forecast_file = Path(
            os.environ.get(
                "MQTT_SCHEDULE_OPENWEATHER_FORECAST_FILE",
                str(base_dir / "ow_records_forecast.json"),
            )
        )
        tempest_data_dir = Path(
            os.environ.get(
                "MQTT_SCHEDULE_TEMPEST_DATA_DIR",
                str(base_dir / "tempest_weather_data"),
            )
        )
        return cls(
            schedule_file=schedule_file,
            controller_file=controller_file,
            access_users_file=Path(
                os.environ.get(
                    "MQTT_SCHEDULE_ACCESS_USERS_FILE",
                    str(base_dir / "airtable_access_users.json"),
                )
            ),
            clients_sysinfo_dir=Path(
                os.environ.get(
                    "MQTT_SCHEDULE_CLIENTS_SYSINFO_DIR",
                    str(base_dir / "clients_sysinfo"),
                )
            ),
            transaction_csv_file=transaction_csv_file,
            temperature_csv_file=temperature_csv_file,
            controller_status_csv_file=controller_status_csv_file,
            csv_backup_dir=csv_backup_dir,
            openweather_current_file=openweather_current_file,
            openweather_forecast_file=openweather_forecast_file,
            tempest_data_dir=tempest_data_dir,
            device_serial_file=Path(
                os.environ.get(
                    "MQTT_SCHEDULE_DEVICE_SERIAL_FILE",
                    str(state_dir / "device_serial.txt"),
                )
            ),
            controller_status_file=controller_status_file,
            controller_offline_after_seconds=int(
                os.environ.get("MQTT_SCHEDULE_CONTROLLER_OFFLINE_AFTER_SECONDS", str(3 * 60))
            ),
            controller_online_recovery_after_seconds=int(
                os.environ.get("MQTT_SCHEDULE_CONTROLLER_ONLINE_RECOVERY_AFTER_SECONDS", str(2 * 60))
            ),
            commissioning_only_destinations=_env_csv("MQTT_SCHEDULE_ONLY_DESTINATIONS"),
            source_serial_override=os.environ.get("MQTT_SCHEDULE_SOURCE_SERIAL_OVERRIDE"),
            tempest_station_id=int(os.environ.get("MQTT_SCHEDULE_TEMPEST_STATION_ID", "201749")),
            openweather_url=os.environ.get("MQTT_SCHEDULE_OPENWEATHER_URL", "https://api.openweathermap.org/data/2.5"),
            openweather_api_key=os.environ.get("MQTT_SCHEDULE_OPENWEATHER_API_KEY"),
            openweather_lat=_env_float("MQTT_SCHEDULE_OPENWEATHER_LAT"),
            openweather_lon=_env_float("MQTT_SCHEDULE_OPENWEATHER_LON"),
            openweather_units=os.environ.get("MQTT_SCHEDULE_OPENWEATHER_UNITS", "imperial"),
            airtable_base_url=os.environ.get("MQTT_SCHEDULE_AIRTABLE_BASE_URL", "https://api.airtable.com/v0"),
            airtable_base_id=os.environ.get("MQTT_SCHEDULE_AIRTABLE_BASE_ID"),
            airtable_api_key=os.environ.get("MQTT_SCHEDULE_AIRTABLE_API_KEY"),
            airtable_controller_table=os.environ.get("MQTT_SCHEDULE_AIRTABLE_CONTROLLER_TABLE", "irrigation-config"),
            airtable_schedule_table=os.environ.get("MQTT_SCHEDULE_AIRTABLE_SCHEDULE_TABLE", "irrigation-schedule"),
            airtable_access_users_table=os.environ.get("MQTT_SCHEDULE_AIRTABLE_ACCESS_USERS_TABLE", "access-users"),
            tempest_base_url=os.environ.get("MQTT_SCHEDULE_TEMPEST_BASE_URL", "https://swd.weatherflow.com/swd/rest"),
            tempest_token=os.environ.get("MQTT_SCHEDULE_TEMPEST_TOKEN"),
            weather_refresh_openweather_seconds=int(os.environ.get("MQTT_SCHEDULE_OPENWEATHER_REFRESH_SECONDS", str(3 * 3600))),
            weather_refresh_tempest_seconds=int(os.environ.get("MQTT_SCHEDULE_TEMPEST_REFRESH_SECONDS", "3600")),
            weather_refresh_run_immediately=_env_bool("MQTT_SCHEDULE_WEATHER_REFRESH_RUN_IMMEDIATELY", False),
            tempest_snapshot_keep=int(os.environ.get("MQTT_SCHEDULE_TEMPEST_SNAPSHOT_KEEP", "5")),
            mqtt_host=os.environ.get("MQTT_SCHEDULE_MQTT_HOST", "localhost"),
            mqtt_port=int(os.environ.get("MQTT_SCHEDULE_MQTT_PORT", "1883")),
            mqtt_keepalive=int(os.environ.get("MQTT_SCHEDULE_MQTT_KEEPALIVE", "60")),
            mqtt_username=os.environ.get("MQTT_SCHEDULE_MQTT_USERNAME"),
            mqtt_password=os.environ.get("MQTT_SCHEDULE_MQTT_PASSWORD"),
            mqtt_online_status_request_enabled=_env_bool("MQTT_SCHEDULE_MQTT_ONLINE_STATUS_REQUEST_ENABLED", True),
            mqtt_input_status_request_enabled=_env_bool("MQTT_SCHEDULE_MQTT_INPUT_STATUS_REQUEST_ENABLED", True),
            mqtt_temperature_request_enabled=_env_bool("MQTT_SCHEDULE_MQTT_TEMPERATURE_REQUEST_ENABLED", True),
            mqtt_online_status_request_seconds=int(os.environ.get("MQTT_SCHEDULE_MQTT_ONLINE_STATUS_REQUEST_SECONDS", "60")),
            mqtt_input_status_request_seconds=int(os.environ.get("MQTT_SCHEDULE_MQTT_INPUT_STATUS_REQUEST_SECONDS", "60")),
            mqtt_temperature_request_seconds=int(os.environ.get("MQTT_SCHEDULE_MQTT_TEMPERATURE_REQUEST_SECONDS", str(20 * 60))),
            mqtt_topic_version=os.environ.get("MQTT_SCHEDULE_MQTT_TOPIC_VERSION", "SPV1.0"),
            mqtt_domain=os.environ.get("MQTT_SCHEDULE_MQTT_DOMAIN", "irrigation"),
            timezone_name=os.environ.get("MQTT_SCHEDULE_TIMEZONE", "America/New_York"),
            hemisphere=os.environ.get("MQTT_SCHEDULE_HEMISPHERE", "north"),
            use_duration_sunrise=_env_bool("MQTT_SCHEDULE_USE_DURATION_SUNRISE", True),
            use_duration_sunset=_env_bool("MQTT_SCHEDULE_USE_DURATION_SUNSET", False),
            program_name=os.environ.get("MQTT_SCHEDULE_PROGRAM_NAME", "mqtt_schedule"),
            program_version=os.environ.get("MQTT_SCHEDULE_PROGRAM_VERSION", "0.1.0"),
            access_groups=_env_csv("MQTT_SCHEDULE_ACCESS_GROUPS"),
            transaction_csv_max_entries=int(os.environ.get("MQTT_SCHEDULE_TRANSACTION_CSV_MAX_ENTRIES", "5000")),
            transaction_csv_backup_count=int(os.environ.get("MQTT_SCHEDULE_TRANSACTION_CSV_BACKUP_COUNT", "10")),
            temperature_csv_max_entries=int(os.environ.get("MQTT_SCHEDULE_TEMPERATURE_CSV_MAX_ENTRIES", "5000")),
            temperature_csv_backup_count=int(os.environ.get("MQTT_SCHEDULE_TEMPERATURE_CSV_BACKUP_COUNT", "10")),
            controller_status_csv_max_entries=int(os.environ.get("MQTT_SCHEDULE_CONTROLLER_STATUS_CSV_MAX_ENTRIES", "5000")),
            controller_status_csv_backup_count=int(os.environ.get("MQTT_SCHEDULE_CONTROLLER_STATUS_CSV_BACKUP_COUNT", "10")),
            rain_now_block_mm=float(os.environ.get("MQTT_SCHEDULE_RAIN_NOW_BLOCK_MM", "2.0")),
            rain_24h_block_mm=float(os.environ.get("MQTT_SCHEDULE_RAIN_24H_BLOCK_MM", "5.0")),
            rain_48h_block_mm=float(os.environ.get("MQTT_SCHEDULE_RAIN_48H_BLOCK_MM", "8.0")),
            rain_7d_block_mm=float(os.environ.get("MQTT_SCHEDULE_RAIN_7D_BLOCK_MM", "15.0")),
            require_latest_within_minutes=int(
                os.environ.get("MQTT_SCHEDULE_REQUIRE_LATEST_WITHIN_MINUTES", "180")
            ),
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> RuntimeSettings:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        settings = cls(
            schedule_file=Path(data["schedule_file"]),
            controller_file=Path(data["controller_file"]),
            access_users_file=Path(data.get("access_users_file", "/etc/mqtt_schedule/airtable_access_users.json")),
            clients_sysinfo_dir=Path(data.get("clients_sysinfo_dir", "/etc/mqtt_schedule/clients_sysinfo")),
            transaction_csv_file=Path(data.get("transaction_csv_file", "/var/lib/mqtt_schedule/transactions.csv")),
            temperature_csv_file=Path(data.get("temperature_csv_file", "/var/lib/mqtt_schedule/temperature.csv")),
            controller_status_csv_file=Path(data.get("controller_status_csv_file", "/var/lib/mqtt_schedule/controller_status_events.csv")),
            csv_backup_dir=Path(data.get("csv_backup_dir", "/var/lib/mqtt_schedule/csv_backup")),
            openweather_current_file=Path(data["openweather_current_file"]),
            openweather_forecast_file=Path(data["openweather_forecast_file"]),
            tempest_data_dir=Path(data["tempest_data_dir"]),
            device_serial_file=Path(data.get("device_serial_file", "/var/lib/mqtt_schedule/device_serial.txt")),
            controller_status_file=Path(data.get("controller_status_file", "/var/lib/mqtt_schedule/controller_status.json")),
            controller_offline_after_seconds=int(data.get("controller_offline_after_seconds", 3 * 60)),
            controller_online_recovery_after_seconds=int(
                data.get("controller_online_recovery_after_seconds", 2 * 60)
            ),
            commissioning_only_destinations=tuple(data.get("commissioning_only_destinations", [])),
            source_serial_override=data.get("source_serial_override"),
            tempest_station_id=int(data.get("tempest_station_id", 201749)),
            openweather_url=data.get("openweather_url", "https://api.openweathermap.org/data/2.5"),
            openweather_api_key=data.get("openweather_api_key"),
            openweather_lat=data.get("openweather_lat"),
            openweather_lon=data.get("openweather_lon"),
            openweather_units=data.get("openweather_units", "imperial"),
            airtable_base_url=data.get("airtable_base_url", "https://api.airtable.com/v0"),
            airtable_base_id=data.get("airtable_base_id"),
            airtable_api_key=data.get("airtable_api_key"),
            airtable_controller_table=data.get("airtable_controller_table", "irrigation-config"),
            airtable_schedule_table=data.get("airtable_schedule_table", "irrigation-schedule"),
            airtable_access_users_table=data.get("airtable_access_users_table", "access-users"),
            tempest_base_url=data.get("tempest_base_url", "https://swd.weatherflow.com/swd/rest"),
            tempest_token=data.get("tempest_token"),
            weather_refresh_openweather_seconds=int(data.get("weather_refresh_openweather_seconds", 3 * 3600)),
            weather_refresh_tempest_seconds=int(data.get("weather_refresh_tempest_seconds", 3600)),
            weather_refresh_run_immediately=bool(data.get("weather_refresh_run_immediately", False)),
            tempest_snapshot_keep=int(data.get("tempest_snapshot_keep", 5)),
            mqtt_host=data.get("mqtt_host", "localhost"),
            mqtt_port=int(data.get("mqtt_port", 1883)),
            mqtt_keepalive=int(data.get("mqtt_keepalive", 60)),
            mqtt_username=data.get("mqtt_username"),
            mqtt_password=data.get("mqtt_password"),
            mqtt_online_status_request_enabled=bool(data.get("mqtt_online_status_request_enabled", True)),
            mqtt_input_status_request_enabled=bool(data.get("mqtt_input_status_request_enabled", True)),
            mqtt_temperature_request_enabled=bool(data.get("mqtt_temperature_request_enabled", True)),
            mqtt_online_status_request_seconds=int(data.get("mqtt_online_status_request_seconds", 60)),
            mqtt_input_status_request_seconds=int(data.get("mqtt_input_status_request_seconds", 60)),
            mqtt_temperature_request_seconds=int(data.get("mqtt_temperature_request_seconds", 20 * 60)),
            mqtt_topic_version=data.get("mqtt_topic_version", "SPV1.0"),
            mqtt_domain=data.get("mqtt_domain", "irrigation"),
            timezone_name=data.get("timezone_name", "America/New_York"),
            hemisphere=data.get("hemisphere", "north"),
            use_duration_sunrise=bool(data.get("use_duration_sunrise", True)),
            use_duration_sunset=bool(data.get("use_duration_sunset", False)),
            program_name=data.get("program_name", "mqtt_schedule"),
            program_version=data.get("program_version", "0.1.0"),
            access_groups=tuple(data.get("access_groups", [])),
            transaction_csv_max_entries=int(data.get("transaction_csv_max_entries", 5000)),
            transaction_csv_backup_count=int(data.get("transaction_csv_backup_count", 10)),
            temperature_csv_max_entries=int(data.get("temperature_csv_max_entries", 5000)),
            temperature_csv_backup_count=int(data.get("temperature_csv_backup_count", 10)),
            controller_status_csv_max_entries=int(data.get("controller_status_csv_max_entries", 5000)),
            controller_status_csv_backup_count=int(data.get("controller_status_csv_backup_count", 10)),
            rain_now_block_mm=float(data.get("rain_now_block_mm", 2.0)),
            rain_24h_block_mm=float(data.get("rain_24h_block_mm", 5.0)),
            rain_48h_block_mm=float(data.get("rain_48h_block_mm", 8.0)),
            rain_7d_block_mm=float(data.get("rain_7d_block_mm", 15.0)),
            require_latest_within_minutes=int(data.get("require_latest_within_minutes", 180)),
        )
        return settings.apply_env_overrides()

    def apply_env_overrides(self) -> RuntimeSettings:
        return RuntimeSettings(
            schedule_file=_env_path("MQTT_SCHEDULE_SCHEDULE_FILE", self.schedule_file),
            controller_file=_env_path("MQTT_SCHEDULE_CONTROLLER_FILE", self.controller_file),
            access_users_file=_env_path("MQTT_SCHEDULE_ACCESS_USERS_FILE", self.access_users_file),
            clients_sysinfo_dir=_env_path("MQTT_SCHEDULE_CLIENTS_SYSINFO_DIR", self.clients_sysinfo_dir),
            transaction_csv_file=_env_path("MQTT_SCHEDULE_TRANSACTION_CSV_FILE", self.transaction_csv_file),
            temperature_csv_file=_env_path("MQTT_SCHEDULE_TEMPERATURE_CSV_FILE", self.temperature_csv_file),
            controller_status_csv_file=_env_path("MQTT_SCHEDULE_CONTROLLER_STATUS_CSV_FILE", self.controller_status_csv_file),
            csv_backup_dir=_env_path("MQTT_SCHEDULE_CSV_BACKUP_DIR", self.csv_backup_dir),
            openweather_current_file=_env_path("MQTT_SCHEDULE_OPENWEATHER_CURRENT_FILE", self.openweather_current_file),
            openweather_forecast_file=_env_path("MQTT_SCHEDULE_OPENWEATHER_FORECAST_FILE", self.openweather_forecast_file),
            tempest_data_dir=_env_path("MQTT_SCHEDULE_TEMPEST_DATA_DIR", self.tempest_data_dir),
            device_serial_file=_env_path("MQTT_SCHEDULE_DEVICE_SERIAL_FILE", self.device_serial_file),
            controller_status_file=_env_path("MQTT_SCHEDULE_CONTROLLER_STATUS_FILE", self.controller_status_file),
            controller_offline_after_seconds=_env_int(
                "MQTT_SCHEDULE_CONTROLLER_OFFLINE_AFTER_SECONDS",
                self.controller_offline_after_seconds,
            ),
            controller_online_recovery_after_seconds=_env_int(
                "MQTT_SCHEDULE_CONTROLLER_ONLINE_RECOVERY_AFTER_SECONDS",
                self.controller_online_recovery_after_seconds,
            ),
            commissioning_only_destinations=_env_csv("MQTT_SCHEDULE_ONLY_DESTINATIONS") or self.commissioning_only_destinations,
            source_serial_override=os.environ.get("MQTT_SCHEDULE_SOURCE_SERIAL_OVERRIDE", self.source_serial_override),
            tempest_station_id=_env_int("MQTT_SCHEDULE_TEMPEST_STATION_ID", self.tempest_station_id),
            openweather_url=os.environ.get("MQTT_SCHEDULE_OPENWEATHER_URL", self.openweather_url),
            openweather_api_key=os.environ.get("MQTT_SCHEDULE_OPENWEATHER_API_KEY", self.openweather_api_key),
            openweather_lat=_env_optional_float("MQTT_SCHEDULE_OPENWEATHER_LAT", self.openweather_lat),
            openweather_lon=_env_optional_float("MQTT_SCHEDULE_OPENWEATHER_LON", self.openweather_lon),
            openweather_units=os.environ.get("MQTT_SCHEDULE_OPENWEATHER_UNITS", self.openweather_units),
            airtable_base_url=os.environ.get("MQTT_SCHEDULE_AIRTABLE_BASE_URL", self.airtable_base_url),
            airtable_base_id=os.environ.get("MQTT_SCHEDULE_AIRTABLE_BASE_ID", self.airtable_base_id),
            airtable_api_key=os.environ.get("MQTT_SCHEDULE_AIRTABLE_API_KEY", self.airtable_api_key),
            airtable_controller_table=os.environ.get(
                "MQTT_SCHEDULE_AIRTABLE_CONTROLLER_TABLE",
                self.airtable_controller_table,
            ),
            airtable_schedule_table=os.environ.get(
                "MQTT_SCHEDULE_AIRTABLE_SCHEDULE_TABLE",
                self.airtable_schedule_table,
            ),
            airtable_access_users_table=os.environ.get(
                "MQTT_SCHEDULE_AIRTABLE_ACCESS_USERS_TABLE",
                self.airtable_access_users_table,
            ),
            tempest_base_url=os.environ.get("MQTT_SCHEDULE_TEMPEST_BASE_URL", self.tempest_base_url),
            tempest_token=os.environ.get("MQTT_SCHEDULE_TEMPEST_TOKEN", self.tempest_token),
            weather_refresh_openweather_seconds=_env_int(
                "MQTT_SCHEDULE_OPENWEATHER_REFRESH_SECONDS",
                self.weather_refresh_openweather_seconds,
            ),
            weather_refresh_tempest_seconds=_env_int(
                "MQTT_SCHEDULE_TEMPEST_REFRESH_SECONDS",
                self.weather_refresh_tempest_seconds,
            ),
            weather_refresh_run_immediately=_env_bool(
                "MQTT_SCHEDULE_WEATHER_REFRESH_RUN_IMMEDIATELY",
                self.weather_refresh_run_immediately,
            ),
            tempest_snapshot_keep=_env_int("MQTT_SCHEDULE_TEMPEST_SNAPSHOT_KEEP", self.tempest_snapshot_keep),
            mqtt_host=os.environ.get("MQTT_SCHEDULE_MQTT_HOST", self.mqtt_host),
            mqtt_port=_env_int("MQTT_SCHEDULE_MQTT_PORT", self.mqtt_port),
            mqtt_keepalive=_env_int("MQTT_SCHEDULE_MQTT_KEEPALIVE", self.mqtt_keepalive),
            mqtt_username=os.environ.get("MQTT_SCHEDULE_MQTT_USERNAME", self.mqtt_username),
            mqtt_password=os.environ.get("MQTT_SCHEDULE_MQTT_PASSWORD", self.mqtt_password),
            mqtt_online_status_request_enabled=_env_bool(
                "MQTT_SCHEDULE_MQTT_ONLINE_STATUS_REQUEST_ENABLED",
                self.mqtt_online_status_request_enabled,
            ),
            mqtt_input_status_request_enabled=_env_bool(
                "MQTT_SCHEDULE_MQTT_INPUT_STATUS_REQUEST_ENABLED",
                self.mqtt_input_status_request_enabled,
            ),
            mqtt_temperature_request_enabled=_env_bool(
                "MQTT_SCHEDULE_MQTT_TEMPERATURE_REQUEST_ENABLED",
                self.mqtt_temperature_request_enabled,
            ),
            mqtt_online_status_request_seconds=_env_int(
                "MQTT_SCHEDULE_MQTT_ONLINE_STATUS_REQUEST_SECONDS",
                self.mqtt_online_status_request_seconds,
            ),
            mqtt_input_status_request_seconds=_env_int(
                "MQTT_SCHEDULE_MQTT_INPUT_STATUS_REQUEST_SECONDS",
                self.mqtt_input_status_request_seconds,
            ),
            mqtt_temperature_request_seconds=_env_int(
                "MQTT_SCHEDULE_MQTT_TEMPERATURE_REQUEST_SECONDS",
                self.mqtt_temperature_request_seconds,
            ),
            mqtt_topic_version=os.environ.get("MQTT_SCHEDULE_MQTT_TOPIC_VERSION", self.mqtt_topic_version),
            mqtt_domain=os.environ.get("MQTT_SCHEDULE_MQTT_DOMAIN", self.mqtt_domain),
            timezone_name=os.environ.get("MQTT_SCHEDULE_TIMEZONE", self.timezone_name),
            hemisphere=os.environ.get("MQTT_SCHEDULE_HEMISPHERE", self.hemisphere),
            use_duration_sunrise=_env_bool("MQTT_SCHEDULE_USE_DURATION_SUNRISE", self.use_duration_sunrise),
            use_duration_sunset=_env_bool("MQTT_SCHEDULE_USE_DURATION_SUNSET", self.use_duration_sunset),
            program_name=os.environ.get("MQTT_SCHEDULE_PROGRAM_NAME", self.program_name),
            program_version=os.environ.get("MQTT_SCHEDULE_PROGRAM_VERSION", self.program_version),
            access_groups=_env_csv("MQTT_SCHEDULE_ACCESS_GROUPS") or self.access_groups,
            transaction_csv_max_entries=_env_int(
                "MQTT_SCHEDULE_TRANSACTION_CSV_MAX_ENTRIES",
                self.transaction_csv_max_entries,
            ),
            transaction_csv_backup_count=_env_int(
                "MQTT_SCHEDULE_TRANSACTION_CSV_BACKUP_COUNT",
                self.transaction_csv_backup_count,
            ),
            temperature_csv_max_entries=_env_int(
                "MQTT_SCHEDULE_TEMPERATURE_CSV_MAX_ENTRIES",
                self.temperature_csv_max_entries,
            ),
            temperature_csv_backup_count=_env_int(
                "MQTT_SCHEDULE_TEMPERATURE_CSV_BACKUP_COUNT",
                self.temperature_csv_backup_count,
            ),
            controller_status_csv_max_entries=_env_int(
                "MQTT_SCHEDULE_CONTROLLER_STATUS_CSV_MAX_ENTRIES",
                self.controller_status_csv_max_entries,
            ),
            controller_status_csv_backup_count=_env_int(
                "MQTT_SCHEDULE_CONTROLLER_STATUS_CSV_BACKUP_COUNT",
                self.controller_status_csv_backup_count,
            ),
            rain_now_block_mm=_env_float_with_default("MQTT_SCHEDULE_RAIN_NOW_BLOCK_MM", self.rain_now_block_mm),
            rain_24h_block_mm=_env_float_with_default("MQTT_SCHEDULE_RAIN_24H_BLOCK_MM", self.rain_24h_block_mm),
            rain_48h_block_mm=_env_float_with_default("MQTT_SCHEDULE_RAIN_48H_BLOCK_MM", self.rain_48h_block_mm),
            rain_7d_block_mm=_env_float_with_default("MQTT_SCHEDULE_RAIN_7D_BLOCK_MM", self.rain_7d_block_mm),
            require_latest_within_minutes=_env_int(
                "MQTT_SCHEDULE_REQUIRE_LATEST_WITHIN_MINUTES",
                self.require_latest_within_minutes,
            ),
        )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    return float(raw)


def _env_optional_float(name: str, default: float | None) -> float | None:
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw.strip() == "":
        return None
    return float(raw)


def _env_float_with_default(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return Path(raw)


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())
