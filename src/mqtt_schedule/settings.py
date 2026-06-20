from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeSettings:
    schedule_file: Path
    controller_file: Path
    openweather_current_file: Path
    openweather_forecast_file: Path
    tempest_data_dir: Path
    device_serial_file: Path
    commissioning_only_destinations: tuple[str, ...] = ()
    source_serial_override: str | None = None
    tempest_station_id: int = 201749
    openweather_url: str = "https://api.openweathermap.org/data/2.5"
    openweather_api_key: str | None = None
    openweather_lat: float | None = None
    openweather_lon: float | None = None
    openweather_units: str = "imperial"
    tempest_base_url: str = "https://swd.weatherflow.com/swd/rest"
    tempest_token: str | None = None
    weather_refresh_openweather_seconds: int = 3 * 3600
    weather_refresh_tempest_seconds: int = 3600
    tempest_snapshot_keep: int = 5
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_keepalive: int = 60
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic_version: str = "SPV1.0"
    mqtt_domain: str = "irrigation"
    timezone_name: str = "America/New_York"
    hemisphere: str = "north"
    use_duration_sunrise: bool = True
    use_duration_sunset: bool = False
    program_name: str = "mqtt_schedule"
    program_version: str = "0.1.0"
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
            openweather_current_file=openweather_current_file,
            openweather_forecast_file=openweather_forecast_file,
            tempest_data_dir=tempest_data_dir,
            device_serial_file=Path(
                os.environ.get(
                    "MQTT_SCHEDULE_DEVICE_SERIAL_FILE",
                    str(state_dir / "device_serial.txt"),
                )
            ),
            commissioning_only_destinations=_env_csv("MQTT_SCHEDULE_ONLY_DESTINATIONS"),
            source_serial_override=os.environ.get("MQTT_SCHEDULE_SOURCE_SERIAL_OVERRIDE"),
            tempest_station_id=int(os.environ.get("MQTT_SCHEDULE_TEMPEST_STATION_ID", "201749")),
            openweather_url=os.environ.get("MQTT_SCHEDULE_OPENWEATHER_URL", "https://api.openweathermap.org/data/2.5"),
            openweather_api_key=os.environ.get("MQTT_SCHEDULE_OPENWEATHER_API_KEY"),
            openweather_lat=_env_float("MQTT_SCHEDULE_OPENWEATHER_LAT"),
            openweather_lon=_env_float("MQTT_SCHEDULE_OPENWEATHER_LON"),
            openweather_units=os.environ.get("MQTT_SCHEDULE_OPENWEATHER_UNITS", "imperial"),
            tempest_base_url=os.environ.get("MQTT_SCHEDULE_TEMPEST_BASE_URL", "https://swd.weatherflow.com/swd/rest"),
            tempest_token=os.environ.get("MQTT_SCHEDULE_TEMPEST_TOKEN"),
            weather_refresh_openweather_seconds=int(os.environ.get("MQTT_SCHEDULE_OPENWEATHER_REFRESH_SECONDS", str(3 * 3600))),
            weather_refresh_tempest_seconds=int(os.environ.get("MQTT_SCHEDULE_TEMPEST_REFRESH_SECONDS", "3600")),
            tempest_snapshot_keep=int(os.environ.get("MQTT_SCHEDULE_TEMPEST_SNAPSHOT_KEEP", "5")),
            mqtt_host=os.environ.get("MQTT_SCHEDULE_MQTT_HOST", "localhost"),
            mqtt_port=int(os.environ.get("MQTT_SCHEDULE_MQTT_PORT", "1883")),
            mqtt_keepalive=int(os.environ.get("MQTT_SCHEDULE_MQTT_KEEPALIVE", "60")),
            mqtt_username=os.environ.get("MQTT_SCHEDULE_MQTT_USERNAME"),
            mqtt_password=os.environ.get("MQTT_SCHEDULE_MQTT_PASSWORD"),
            mqtt_topic_version=os.environ.get("MQTT_SCHEDULE_MQTT_TOPIC_VERSION", "SPV1.0"),
            mqtt_domain=os.environ.get("MQTT_SCHEDULE_MQTT_DOMAIN", "irrigation"),
            timezone_name=os.environ.get("MQTT_SCHEDULE_TIMEZONE", "America/New_York"),
            hemisphere=os.environ.get("MQTT_SCHEDULE_HEMISPHERE", "north"),
            use_duration_sunrise=_env_bool("MQTT_SCHEDULE_USE_DURATION_SUNRISE", True),
            use_duration_sunset=_env_bool("MQTT_SCHEDULE_USE_DURATION_SUNSET", False),
            program_name=os.environ.get("MQTT_SCHEDULE_PROGRAM_NAME", "mqtt_schedule"),
            program_version=os.environ.get("MQTT_SCHEDULE_PROGRAM_VERSION", "0.1.0"),
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
        return cls(
            schedule_file=Path(data["schedule_file"]),
            controller_file=Path(data["controller_file"]),
            openweather_current_file=Path(data["openweather_current_file"]),
            openweather_forecast_file=Path(data["openweather_forecast_file"]),
            tempest_data_dir=Path(data["tempest_data_dir"]),
            device_serial_file=Path(data.get("device_serial_file", "/var/lib/mqtt_schedule/device_serial.txt")),
            commissioning_only_destinations=tuple(data.get("commissioning_only_destinations", [])),
            source_serial_override=data.get("source_serial_override"),
            tempest_station_id=int(data.get("tempest_station_id", 201749)),
            openweather_url=data.get("openweather_url", "https://api.openweathermap.org/data/2.5"),
            openweather_api_key=data.get("openweather_api_key"),
            openweather_lat=data.get("openweather_lat"),
            openweather_lon=data.get("openweather_lon"),
            openweather_units=data.get("openweather_units", "imperial"),
            tempest_base_url=data.get("tempest_base_url", "https://swd.weatherflow.com/swd/rest"),
            tempest_token=data.get("tempest_token"),
            weather_refresh_openweather_seconds=int(data.get("weather_refresh_openweather_seconds", 3 * 3600)),
            weather_refresh_tempest_seconds=int(data.get("weather_refresh_tempest_seconds", 3600)),
            tempest_snapshot_keep=int(data.get("tempest_snapshot_keep", 5)),
            mqtt_host=data.get("mqtt_host", "localhost"),
            mqtt_port=int(data.get("mqtt_port", 1883)),
            mqtt_keepalive=int(data.get("mqtt_keepalive", 60)),
            mqtt_username=data.get("mqtt_username"),
            mqtt_password=data.get("mqtt_password"),
            mqtt_topic_version=data.get("mqtt_topic_version", "SPV1.0"),
            mqtt_domain=data.get("mqtt_domain", "irrigation"),
            timezone_name=data.get("timezone_name", "America/New_York"),
            hemisphere=data.get("hemisphere", "north"),
            use_duration_sunrise=bool(data.get("use_duration_sunrise", True)),
            use_duration_sunset=bool(data.get("use_duration_sunset", False)),
            program_name=data.get("program_name", "mqtt_schedule"),
            program_version=data.get("program_version", "0.1.0"),
            rain_now_block_mm=float(data.get("rain_now_block_mm", 2.0)),
            rain_24h_block_mm=float(data.get("rain_24h_block_mm", 5.0)),
            rain_48h_block_mm=float(data.get("rain_48h_block_mm", 8.0)),
            rain_7d_block_mm=float(data.get("rain_7d_block_mm", 15.0)),
            require_latest_within_minutes=int(data.get("require_latest_within_minutes", 180)),
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


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())
