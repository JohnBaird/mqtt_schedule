from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .mongo_ingestion import IngestionRunRecord, MongoIngestionRunRepository


logger = logging.getLogger("mqtt_schedule.mongo_tempest")


@dataclass(frozen=True)
class TempestIngestResult:
    run_id: str
    source: str
    file_path: str
    file_hash: str
    status: str
    inserted: int
    updated: int
    skipped: int
    error: str | None = None


class TempestMongoIngestService:
    def __init__(
        self,
        *,
        stations_collection: Any,
        tempest_flow_collection: Any,
        ingestion_runs: MongoIngestionRunRepository,
    ) -> None:
        self.stations_collection = stations_collection
        self.tempest_flow_collection = tempest_flow_collection
        self.ingestion_runs = ingestion_runs

    def ingest_station_meta(self, file_path: str | Path) -> TempestIngestResult:
        return self._ingest_file(
            source="tempest_flow:station_meta",
            file_path=file_path,
            handler=self._handle_station_meta_payload,
        )

    def ingest_station_obs(self, file_path: str | Path) -> TempestIngestResult:
        return self._ingest_file(
            source="tempest_flow:station_obs",
            file_path=file_path,
            handler=self._handle_station_obs_payload,
        )

    def ingest_directory(self, data_dir: str | Path) -> list[TempestIngestResult]:
        path = Path(data_dir)
        results: list[TempestIngestResult] = []
        meta_file = path / "station_meta.json"
        if meta_file.exists():
            results.append(self.ingest_station_meta(meta_file))
        for obs_file in sorted(path.glob("station_obs_*.json")):
            if obs_file.name.count("_") > 2:
                continue
            results.append(self.ingest_station_obs(obs_file))
        return results

    def _ingest_file(self, *, source: str, file_path: str | Path, handler) -> TempestIngestResult:
        path = Path(file_path)
        if not path.exists():
            return TempestIngestResult(
                run_id=uuid4().hex[:24],
                source=source,
                file_path=str(path),
                file_hash="",
                status="error",
                inserted=0,
                updated=0,
                skipped=0,
                error=f"file not found: {path}",
            )

        file_hash = self.ingestion_runs.read_file_hash(path)
        existing = self.ingestion_runs.find_existing(source=source, file_hash=file_hash)
        if existing:
            return TempestIngestResult(
                run_id=str(existing.get("run_id", uuid4().hex[:24])),
                source=source,
                file_path=str(path),
                file_hash=file_hash,
                status="skipped",
                inserted=0,
                updated=0,
                skipped=1,
                error=None,
            )

        run_id = uuid4().hex[:24]
        ingested_at_utc = self.ingestion_runs.utcnow()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            inserted, updated, skipped = handler(payload=payload, file_path=str(path))
            result = TempestIngestResult(
                run_id=run_id,
                source=source,
                file_path=str(path),
                file_hash=file_hash,
                status="ok",
                inserted=inserted,
                updated=updated,
                skipped=skipped,
                error=None,
            )
        except Exception as exc:
            result = TempestIngestResult(
                run_id=run_id,
                source=source,
                file_path=str(path),
                file_hash=file_hash,
                status="error",
                inserted=0,
                updated=0,
                skipped=0,
                error=str(exc),
            )

        self.ingestion_runs.upsert_record(
            IngestionRunRecord(
                run_id=result.run_id,
                source=result.source,
                file_path=result.file_path,
                file_hash=result.file_hash,
                status=result.status,
                inserted=result.inserted,
                updated=result.updated,
                skipped=result.skipped,
                error=result.error,
                ingested_at_utc=ingested_at_utc,
            )
        )
        logger.info(
            "tempest_mongo_ingest_complete source=%s status=%s inserted=%s updated=%s skipped=%s file=%s",
            result.source,
            result.status,
            result.inserted,
            result.updated,
            result.skipped,
            result.file_path,
        )
        return result

    def _handle_station_meta_payload(self, *, payload: dict[str, Any], file_path: str) -> tuple[int, int, int]:
        stations = payload.get("stations", [])
        if not stations:
            raise ValueError("station_meta has no stations[]")

        inserted = updated = skipped = 0
        for station in stations:
            station_id = station.get("station_id") or station.get("location_id")
            if not station_id:
                skipped += 1
                continue
            document = {
                "station_id": int(station_id),
                "station_key": f"tempest:{int(station_id)}",
                "timezone": station.get("timezone"),
                "latitude": station.get("latitude"),
                "longitude": station.get("longitude"),
                "public_name": station.get("public_name"),
                "name": station.get("name"),
                "location_id": station.get("location_id"),
                "updated_from_file": file_path,
                "updated_at_utc": datetime.now(timezone.utc),
                "raw": station,
            }
            result = self.stations_collection.update_one(
                {"station_id": int(station_id)},
                {"$set": document, "$setOnInsert": {"created_at_utc": datetime.now(timezone.utc)}},
                upsert=True,
            )
            ins, upd, skp = _classify_upsert_result(result)
            inserted += ins
            updated += upd
            skipped += skp
        return inserted, updated, skipped

    def _handle_station_obs_payload(self, *, payload: dict[str, Any], file_path: str) -> tuple[int, int, int]:
        station_id = payload.get("station_id")
        if station_id is None:
            raise ValueError("station_obs missing station_id")

        station_id_int = int(station_id)
        station_key = f"tempest:{station_id_int}"
        units = payload.get("station_units", {}) or {}
        obs_list = payload.get("obs", [])
        if not obs_list:
            raise ValueError("station_obs has no obs[]")

        inserted = updated = skipped = 0
        for obs in obs_list:
            ts = obs.get("timestamp")
            if ts is None:
                skipped += 1
                continue
            observed_epoch_s = int(ts)
            observed_at_utc = datetime.fromtimestamp(observed_epoch_s, tz=timezone.utc)
            document = {
                "station_id": station_id_int,
                "station_key": station_key,
                "observed_epoch_s": observed_epoch_s,
                "observed_at_utc": observed_at_utc,
                "timezone": payload.get("timezone"),
                "elevation_m": payload.get("elevation"),
                "latitude": payload.get("latitude"),
                "longitude": payload.get("longitude"),
                "public_name": payload.get("public_name"),
                "station_name": payload.get("station_name"),
                "units": units,
                "norm": self._normalize_obs_metric(obs=obs, units=units),
                "raw": obs,
                "updated_from_file": file_path,
                "updated_at_utc": datetime.now(timezone.utc),
            }
            result = self.tempest_flow_collection.update_one(
                {"station_id": station_id_int, "observed_epoch_s": observed_epoch_s},
                {"$set": document, "$setOnInsert": {"created_at_utc": datetime.now(timezone.utc)}},
                upsert=True,
            )
            ins, upd, skp = _classify_upsert_result(result)
            inserted += ins
            updated += upd
            skipped += skp
        return inserted, updated, skipped

    def _normalize_obs_metric(self, *, obs: dict[str, Any], units: dict[str, Any]) -> dict[str, Any]:
        units_temp = str(units.get("units_temp") or "").lower()
        units_precip = str(units.get("units_precip") or "").lower()
        units_wind = str(units.get("units_wind") or "").lower()

        def as_float(value: Any) -> float | None:
            try:
                if value is None:
                    return None
                return float(value)
            except Exception:
                return None

        def f_to_c(value: float) -> float:
            return (value - 32.0) * (5.0 / 9.0)

        def in_to_mm(value: float) -> float:
            return value * 25.4

        def mph_to_mps(value: float) -> float:
            return value * 0.44704

        def mph_to_kmh(value: float) -> float:
            return value * 1.609344

        def temp_to_c(value: float | None) -> float | None:
            if value is None:
                return None
            if units_temp == "f":
                return f_to_c(value)
            return value

        def precip_to_mm(value: float | None) -> float | None:
            if value is None:
                return None
            if units_precip == "in":
                return in_to_mm(value)
            return value

        def wind_to_mps(value: float | None) -> float | None:
            if value is None:
                return None
            if units_wind == "mph":
                return mph_to_mps(value)
            if units_wind in {"km/h", "kph"}:
                return value / 3.6
            return value

        def wind_to_kmh(value: float | None) -> float | None:
            if value is None:
                return None
            if units_wind == "mph":
                return mph_to_kmh(value)
            if units_wind == "m/s":
                return value * 3.6
            return value

        wind_avg = as_float(obs.get("wind_avg"))
        wind_gust = as_float(obs.get("wind_gust"))
        wind_lull = as_float(obs.get("wind_lull"))
        return {
            "temp_c": {
                "air": temp_to_c(as_float(obs.get("air_temperature"))),
                "dew_point": temp_to_c(as_float(obs.get("dew_point"))),
                "feels_like": temp_to_c(as_float(obs.get("feels_like"))),
                "wet_bulb": temp_to_c(as_float(obs.get("wet_bulb_temperature"))),
            },
            "pressure_hpa": {
                "station": as_float(obs.get("station_pressure")),
                "sea_level": as_float(obs.get("sea_level_pressure")),
                "barometric": as_float(obs.get("barometric_pressure")),
            },
            "humidity_pct": as_float(obs.get("relative_humidity")),
            "precip_mm": {
                "instant": precip_to_mm(as_float(obs.get("precip"))),
                "last_1hr": precip_to_mm(as_float(obs.get("precip_accum_last_1hr"))),
                "local_day": precip_to_mm(as_float(obs.get("precip_accum_local_day"))),
                "yesterday_final": precip_to_mm(as_float(obs.get("precip_accum_local_yesterday_final"))),
            },
            "wind": {
                "avg_mps": wind_to_mps(wind_avg),
                "gust_mps": wind_to_mps(wind_gust),
                "lull_mps": wind_to_mps(wind_lull),
                "avg_kmh": wind_to_kmh(wind_avg),
                "gust_kmh": wind_to_kmh(wind_gust),
                "lull_kmh": wind_to_kmh(wind_lull),
                "direction_deg": obs.get("wind_direction"),
            },
            "solar_radiation_wm2": as_float(obs.get("solar_radiation")),
            "uv_index": as_float(obs.get("uv")),
            "brightness": as_float(obs.get("brightness")),
            "lightning": {
                "count": obs.get("lightning_strike_count"),
                "last_1hr": obs.get("lightning_strike_count_last_1hr"),
                "last_3hr": obs.get("lightning_strike_count_last_3hr"),
            },
        }


def _classify_upsert_result(result: Any) -> tuple[int, int, int]:
    inserted = 1 if getattr(result, "upserted_id", None) is not None else 0
    updated = 1 if inserted == 0 and getattr(result, "modified_count", 0) > 0 else 0
    skipped = 1 if inserted == 0 and updated == 0 else 0
    return inserted, updated, skipped
