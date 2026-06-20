from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .app import IrrigationPolicyService, SunTimesProvider
from .domain import IrrigationDecision, SunTimes

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


@dataclass(frozen=True)
class TempestObservation:
    observed_at_utc: datetime
    station_id: int
    timezone_name: str
    precip_mm_instant: float
    precip_mm_last_1h: float
    precip_mm_local_day: float
    precip_mm_yesterday_final: float


class OpenWeatherFileSunTimesProvider(SunTimesProvider):
    def __init__(self, current_file: str | Path, timezone_name: str) -> None:
        self.current_file = Path(current_file)
        self.timezone_name = timezone_name

    def get_sun_times(self, now: datetime) -> SunTimes:
        payload = json.loads(self.current_file.read_text(encoding="utf-8"))
        sys_block = payload.get("data", {}).get("sys", {})
        timezone_offset_seconds = int(payload.get("data", {}).get("timezone") or 0)
        sunrise_epoch = int(sys_block["sunrise"])
        sunset_epoch = int(sys_block["sunset"])
        return SunTimes(
            sunrise_seconds=_epoch_to_local_seconds_since_midnight(
                sunrise_epoch,
                self.timezone_name,
                fallback_offset_seconds=timezone_offset_seconds,
            ),
            sunset_seconds=_epoch_to_local_seconds_since_midnight(
                sunset_epoch,
                self.timezone_name,
                fallback_offset_seconds=timezone_offset_seconds,
            ),
        )


class TempestFileRainPolicy(IrrigationPolicyService):
    def __init__(
        self,
        tempest_data_dir: str | Path,
        *,
        station_id: int,
        rain_now_block_mm: float,
        rain_24h_block_mm: float,
        rain_48h_block_mm: float,
        rain_7d_block_mm: float,
        require_latest_within_minutes: int = 180,
    ) -> None:
        self.tempest_data_dir = Path(tempest_data_dir)
        self.station_id = int(station_id)
        self.rain_now_block_mm = float(rain_now_block_mm)
        self.rain_24h_block_mm = float(rain_24h_block_mm)
        self.rain_48h_block_mm = float(rain_48h_block_mm)
        self.rain_7d_block_mm = float(rain_7d_block_mm)
        self.require_latest_within_minutes = int(require_latest_within_minutes)

    def decide(self, now: datetime) -> IrrigationDecision:
        current = self._load_current_observation()
        history = self._load_historical_observations()

        previous_days = self._previous_completed_days(current, history)
        rain_1h = current.precip_mm_last_1h
        rain_24h = current.precip_mm_local_day + current.precip_mm_yesterday_final
        rain_48h = rain_24h + sum(previous_days[:1])
        rain_7d = rain_24h + sum(previous_days[:5])

        freshness_seconds = int((now.astimezone(timezone.utc) - current.observed_at_utc).total_seconds())
        stale = freshness_seconds > self.require_latest_within_minutes * 60

        metrics = {
            "station_id": current.station_id,
            "timezone": current.timezone_name,
            "now_utc": now.astimezone(timezone.utc).isoformat(),
            "latest_obs_utc": current.observed_at_utc.isoformat(),
            "freshness_seconds": freshness_seconds,
            "stale": stale,
            "rain_mm": {
                "last_1h": rain_1h,
                "last_24h": rain_24h,
                "last_48h": rain_48h,
                "last_7d": rain_7d,
                "local_day_now": current.precip_mm_local_day,
            },
            "thresholds_mm": {
                "rain_now_block": self.rain_now_block_mm,
                "rain_24h_block": self.rain_24h_block_mm,
                "rain_48h_block": self.rain_48h_block_mm,
                "rain_7d_block": self.rain_7d_block_mm,
            },
            "notes": [
                "Tempest is source-of-truth for actual rain.",
                "File-backed policy uses current last_1hr plus accumulated completed daily totals.",
            ],
        }

        if rain_1h >= self.rain_now_block_mm:
            return IrrigationDecision(False, "RAIN_RECENT_1H", metrics)
        if rain_24h >= self.rain_24h_block_mm:
            return IrrigationDecision(False, "RAIN_24H_ENOUGH", metrics)
        if rain_48h >= self.rain_48h_block_mm:
            return IrrigationDecision(False, "RAIN_48H_ENOUGH", metrics)
        if rain_7d >= self.rain_7d_block_mm:
            return IrrigationDecision(False, "RAIN_7D_ENOUGH", metrics)
        return IrrigationDecision(True, "OK", metrics)

    def _load_current_observation(self) -> TempestObservation:
        current_path = self.tempest_data_dir / f"station_obs_{self.station_id}.json"
        return self._load_observation_file(current_path)

    def _load_historical_observations(self) -> list[TempestObservation]:
        pattern = f"station_obs_{self.station_id}_*.json"
        observations = [self._load_observation_file(path) for path in sorted(self.tempest_data_dir.glob(pattern))]
        observations.sort(key=lambda item: item.observed_at_utc, reverse=True)
        return observations

    def _load_observation_file(self, path: Path) -> TempestObservation:
        payload = json.loads(path.read_text(encoding="utf-8"))
        obs = (payload.get("obs") or [None])[0]
        if not isinstance(obs, dict):
            raise ValueError(f"Tempest observation file missing obs[0]: {path}")

        station_id = int(payload.get("station_id") or self.station_id)
        timezone_name = str(payload.get("timezone") or "UTC")
        units_precip = str(payload.get("station_units", {}).get("units_precip") or "mm").lower()

        return TempestObservation(
            observed_at_utc=datetime.fromtimestamp(int(obs["timestamp"]), tz=timezone.utc),
            station_id=station_id,
            timezone_name=timezone_name,
            precip_mm_instant=_precip_to_mm(obs.get("precip"), units_precip),
            precip_mm_last_1h=_precip_to_mm(obs.get("precip_accum_last_1hr"), units_precip),
            precip_mm_local_day=_precip_to_mm(obs.get("precip_accum_local_day"), units_precip),
            precip_mm_yesterday_final=_precip_to_mm(obs.get("precip_accum_local_yesterday_final"), units_precip),
        )

    @staticmethod
    def _previous_completed_days(
        current: TempestObservation,
        history: list[TempestObservation],
    ) -> list[float]:
        current_local_date = _local_date(current.observed_at_utc, current.timezone_name)
        completed: list[float] = []
        seen_dates: set[str] = set()

        for observation in history:
            local_date = _local_date(observation.observed_at_utc, observation.timezone_name)
            if local_date >= current_local_date:
                continue
            key = local_date.isoformat()
            if key in seen_dates:
                continue
            seen_dates.add(key)
            completed.append(observation.precip_mm_local_day)

        return completed


def _precip_to_mm(value: object, units_precip: str) -> float:
    try:
        numeric = float(value or 0.0)
    except (TypeError, ValueError):
        numeric = 0.0

    if units_precip == "in":
        return numeric * 25.4
    return numeric


def _epoch_to_local_seconds_since_midnight(
    epoch_seconds: int,
    timezone_name: str,
    *,
    fallback_offset_seconds: int = 0,
) -> int:
    zone = _safe_zoneinfo(timezone_name)
    if zone is not None:
        dt_local = datetime.fromtimestamp(epoch_seconds, tz=zone)
    else:
        dt_local = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
        dt_local = dt_local + timedelta(seconds=fallback_offset_seconds)
    return dt_local.hour * 3600 + dt_local.minute * 60 + dt_local.second


def _local_date(dt_utc: datetime, timezone_name: str):
    zone = _safe_zoneinfo(timezone_name)
    if zone is not None:
        return dt_utc.astimezone(zone).date()
    return dt_utc.date()


def _safe_zoneinfo(timezone_name: str):
    if ZoneInfo is None:  # pragma: no cover
        return None
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return None
