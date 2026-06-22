from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .mongo_ingestion import IngestionRunRecord, MongoIngestionRunRepository


logger = logging.getLogger("mqtt_schedule.mongo_openweather")


@dataclass(frozen=True)
class OpenWeatherIngestResult:
    run_id: str
    source: str
    file_path: str
    file_hash: str
    status: str
    inserted: int
    updated: int
    skipped: int
    error: str | None = None


class OpenWeatherMongoIngestService:
    def __init__(
        self,
        *,
        open_weather_collection: Any,
        ingestion_runs: MongoIngestionRunRepository,
    ) -> None:
        self.open_weather_collection = open_weather_collection
        self.ingestion_runs = ingestion_runs

    def ingest_current(self, file_path: str | Path) -> OpenWeatherIngestResult:
        return self._ingest_file(
            source="open_weather:current",
            file_path=file_path,
            handler=self._handle_current_payload,
        )

    def ingest_forecast(self, file_path: str | Path) -> OpenWeatherIngestResult:
        return self._ingest_file(
            source="open_weather:forecast",
            file_path=file_path,
            handler=self._handle_forecast_payload,
        )

    def ingest_files(
        self,
        *,
        current_file: str | Path,
        forecast_file: str | Path,
    ) -> list[OpenWeatherIngestResult]:
        return [
            self.ingest_current(current_file),
            self.ingest_forecast(forecast_file),
        ]

    def _ingest_file(self, *, source: str, file_path: str | Path, handler) -> OpenWeatherIngestResult:
        path = Path(file_path)
        if not path.exists():
            return OpenWeatherIngestResult(
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
            return OpenWeatherIngestResult(
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
            result = OpenWeatherIngestResult(
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
            result = OpenWeatherIngestResult(
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
            "openweather_mongo_ingest_complete source=%s status=%s inserted=%s updated=%s skipped=%s file=%s",
            result.source,
            result.status,
            result.inserted,
            result.updated,
            result.skipped,
            result.file_path,
        )
        return result

    def _handle_current_payload(self, *, payload: dict[str, Any], file_path: str) -> tuple[int, int, int]:
        this_file = payload.get("this_file") or {}
        data = payload.get("data") or {}
        if not data:
            raise ValueError("openweather current file has no data")

        observed_epoch_s = int(data.get("dt") or 0)
        if observed_epoch_s <= 0:
            raise ValueError("openweather current file missing data.dt")

        place_id = int(data.get("id") or 0)
        if place_id <= 0:
            raise ValueError("openweather current file missing data.id")

        observed_at_utc = datetime.fromtimestamp(observed_epoch_s, tz=timezone.utc)
        document = {
            "place_id": place_id,
            "station_key": f"openweather:{place_id}",
            "provider_endpoint": str(this_file.get("endpoint") or "weather"),
            "observed_epoch_s": observed_epoch_s,
            "observed_at_utc": observed_at_utc,
            "coord": data.get("coord"),
            "timezone_offset_s": data.get("timezone"),
            "place_name": data.get("name"),
            "country": (data.get("sys") or {}).get("country"),
            "this_file": this_file,
            "norm": self._normalize_openweather_metric(data),
            "raw": data,
            "updated_from_file": file_path,
            "updated_at_utc": datetime.now(timezone.utc),
        }
        result = self.open_weather_collection.update_one(
            {
                "place_id": place_id,
                "provider_endpoint": document["provider_endpoint"],
                "observed_epoch_s": observed_epoch_s,
            },
            {"$set": document, "$setOnInsert": {"created_at_utc": datetime.now(timezone.utc)}},
            upsert=True,
        )
        return _classify_upsert_result(result)

    def _handle_forecast_payload(self, *, payload: dict[str, Any], file_path: str) -> tuple[int, int, int]:
        this_file = payload.get("this_file") or {}
        city = payload.get("data", {}).get("city") or payload.get("city") or {}
        items = payload.get("data", {}).get("list") or payload.get("list") or []
        if not items:
            raise ValueError("openweather forecast file has no list[]")

        place_id = int(city.get("id") or 0)
        if place_id <= 0:
            raise ValueError("openweather forecast file missing city.id")

        inserted = updated = skipped = 0
        for item in items:
            observed_epoch_s = int(item.get("dt") or 0)
            if observed_epoch_s <= 0:
                skipped += 1
                continue
            observed_at_utc = datetime.fromtimestamp(observed_epoch_s, tz=timezone.utc)
            document = {
                "place_id": place_id,
                "station_key": f"openweather:{place_id}",
                "provider_endpoint": str(this_file.get("endpoint") or "forecast"),
                "observed_epoch_s": observed_epoch_s,
                "observed_at_utc": observed_at_utc,
                "coord": city.get("coord"),
                "timezone_offset_s": city.get("timezone"),
                "place_name": city.get("name"),
                "country": city.get("country"),
                "city": city,
                "forecast_text_local": item.get("dt_txt"),
                "this_file": this_file,
                "norm": self._normalize_openweather_metric(item),
                "raw": item,
                "updated_from_file": file_path,
                "updated_at_utc": datetime.now(timezone.utc),
            }
            result = self.open_weather_collection.update_one(
                {
                    "place_id": place_id,
                    "provider_endpoint": document["provider_endpoint"],
                    "observed_epoch_s": observed_epoch_s,
                },
                {"$set": document, "$setOnInsert": {"created_at_utc": datetime.now(timezone.utc)}},
                upsert=True,
            )
            ins, upd, skp = _classify_upsert_result(result)
            inserted += ins
            updated += upd
            skipped += skp
        return inserted, updated, skipped

    def _normalize_openweather_metric(self, payload: dict[str, Any]) -> dict[str, Any]:
        main = payload.get("main") or {}
        wind = payload.get("wind") or {}
        clouds = payload.get("clouds") or {}
        rain = payload.get("rain") or {}
        snow = payload.get("snow") or {}
        weather = payload.get("weather") or []

        def as_float(value: Any) -> float | None:
            try:
                if value is None:
                    return None
                return float(value)
            except Exception:
                return None

        return {
            "unit_guess": {
                "temperature": "c_or_f_from_openweather_units",
                "pressure": "hpa",
                "wind_speed": "mps",
                "precip": "mm",
            },
            "temp_c": {
                "temp": as_float(main.get("temp")),
                "feels_like": as_float(main.get("feels_like")),
                "temp_min": as_float(main.get("temp_min")),
                "temp_max": as_float(main.get("temp_max")),
            },
            "humidity_pct": as_float(main.get("humidity")),
            "pressure_hpa": {
                "station": as_float(main.get("pressure")),
                "sea_level": as_float(main.get("sea_level")),
                "ground_level": as_float(main.get("grnd_level")),
            },
            "wind": {
                "speed_mps": as_float(wind.get("speed")),
                "gust_mps": as_float(wind.get("gust")),
                "direction_deg": as_float(wind.get("deg")),
            },
            "clouds_pct": as_float(clouds.get("all")),
            "visibility_m": as_float(payload.get("visibility")),
            "pop": as_float(payload.get("pop")),
            "precip_mm": {
                "rain_1h": as_float(rain.get("1h")),
                "rain_3h": as_float(rain.get("3h")),
                "snow_1h": as_float(snow.get("1h")),
                "snow_3h": as_float(snow.get("3h")),
            },
            "weather": [
                {
                    "id": item.get("id"),
                    "main": item.get("main"),
                    "description": item.get("description"),
                    "icon": item.get("icon"),
                }
                for item in weather
                if isinstance(item, dict)
            ],
        }


def _classify_upsert_result(result: Any) -> tuple[int, int, int]:
    inserted = 1 if getattr(result, "upserted_id", None) is not None else 0
    updated = 1 if inserted == 0 and getattr(result, "modified_count", 0) > 0 else 0
    skipped = 1 if inserted == 0 and updated == 0 else 0
    return inserted, updated, skipped
