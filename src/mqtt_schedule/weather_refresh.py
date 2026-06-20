from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import requests


logger = logging.getLogger("mqtt_schedule.weather_refresh")


class RefreshJob:
    def refresh(self) -> None:
        raise NotImplementedError


@dataclass(frozen=True)
class OpenWeatherRefreshSettings:
    base_url: str
    api_key: str
    lat: float
    lon: float
    units: str
    current_file: Path
    forecast_file: Path
    timeout_seconds: int = 20


class OpenWeatherRefresher(RefreshJob):
    def __init__(self, settings: OpenWeatherRefreshSettings) -> None:
        self.settings = settings

    def refresh(self) -> None:
        logger.info(
            "openweather_refresh_start current_file=%s forecast_file=%s",
            self.settings.current_file,
            self.settings.forecast_file,
        )
        self._refresh_endpoint("weather", self.settings.current_file)
        self._refresh_endpoint("forecast", self.settings.forecast_file)
        logger.info("openweather_refresh_complete")

    def _refresh_endpoint(self, endpoint: str, target_file: Path) -> None:
        params = {
            "lat": self.settings.lat,
            "lon": self.settings.lon,
            "appid": self.settings.api_key,
            "units": self.settings.units,
        }
        url = f"{self.settings.base_url.rstrip('/')}/{endpoint}"
        started = monotonic()
        response = requests.get(url, params=params, timeout=self.settings.timeout_seconds)
        response.raise_for_status()
        payload = {
            "this_file": {
                "endpoint": endpoint,
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "latency_ms": int((monotonic() - started) * 1000),
            },
            "data": response.json(),
        }
        _write_json(target_file, payload)
        logger.info(
            "openweather_endpoint_refreshed endpoint=%s target_file=%s latency_ms=%s",
            endpoint,
            target_file,
            payload["this_file"]["latency_ms"],
        )


@dataclass(frozen=True)
class TempestRefreshSettings:
    base_url: str
    token: str
    data_dir: Path
    snapshot_keep: int = 5
    timeout_seconds: int = 20


class TempestRefresher(RefreshJob):
    SUPPORTED_DEVICE_TYPES = {"ST", "SKY", "AR"}

    def __init__(self, settings: TempestRefreshSettings) -> None:
        self.settings = settings
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)

    def refresh(self) -> None:
        logger.info("tempest_refresh_start data_dir=%s", self.settings.data_dir)
        stations = self._get_json(f"{self.settings.base_url.rstrip('/')}/stations?{urlencode({'token': self.settings.token})}")
        self._write_current_and_daily_snapshot("station_meta.json", stations)

        for station in stations.get("stations", []):
            station_id = int(station["station_id"])
            station_obs = self._get_json(
                f"{self.settings.base_url.rstrip('/')}/observations/station/{station_id}?{urlencode({'token': self.settings.token})}"
            )
            self._write_current_and_daily_snapshot(f"station_obs_{station_id}.json", station_obs)

            for device in station.get("devices", []) or []:
                if device.get("device_type") not in self.SUPPORTED_DEVICE_TYPES:
                    continue
                device_id = int(device["device_id"])
                device_obs = self._get_json(
                    f"{self.settings.base_url.rstrip('/')}/observations/device/{device_id}?{urlencode({'token': self.settings.token})}"
                )
                self._write_current_and_daily_snapshot(f"device_obs_{device_id}.json", device_obs)

        _write_json(self.settings.data_dir / "last_run.json", {"epoch": int(time())})
        logger.info("tempest_refresh_complete data_dir=%s", self.settings.data_dir)

    def _get_json(self, url: str) -> dict:
        req = Request(url, method="GET")
        with urlopen(req, timeout=self.settings.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _write_current_and_daily_snapshot(self, base_filename: str, payload: dict) -> None:
        current_path = self.settings.data_dir / base_filename
        _write_json(current_path, payload)

        snapshot_filename = _snapshot_name(base_filename, datetime.now(timezone.utc))
        snapshot_path = self.settings.data_dir / snapshot_filename
        if not snapshot_path.exists():
            _write_json(snapshot_path, payload)

        _enforce_snapshot_retention(self.settings.data_dir, base_filename, self.settings.snapshot_keep)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def _snapshot_name(base_filename: str, now_utc: datetime) -> str:
    stem = Path(base_filename).stem
    suffix = Path(base_filename).suffix
    return f"{stem}_{now_utc.strftime('%Y%m%d')}{suffix}"


def _enforce_snapshot_retention(data_dir: Path, base_filename: str, keep: int) -> None:
    stem = Path(base_filename).stem
    suffix = Path(base_filename).suffix
    snapshots = sorted(data_dir.glob(f"{stem}_*{suffix}"))
    while len(snapshots) > keep:
        oldest = snapshots.pop(0)
        oldest.unlink(missing_ok=True)
