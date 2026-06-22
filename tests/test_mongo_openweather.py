from __future__ import annotations

import json
from pathlib import Path

from mqtt_schedule.mongo_ingestion import MongoIngestionRunRepository
from mqtt_schedule.mongo_openweather import OpenWeatherMongoIngestService


class FakeUpdateResult:
    def __init__(self, *, upserted_id=None, modified_count=0) -> None:
        self.upserted_id = upserted_id
        self.modified_count = modified_count


class FakeCollection:
    def __init__(self) -> None:
        self.update_calls: list[tuple[dict, dict, bool]] = []
        self.find_one_result = None

    def update_one(self, query, update, upsert=False):
        self.update_calls.append((query, update, upsert))
        if "$setOnInsert" in update and len(self.update_calls) == 1:
            return FakeUpdateResult(upserted_id="new-doc")
        return FakeUpdateResult(modified_count=1)

    def find_one(self, query):
        return self.find_one_result


def test_openweather_mongo_ingest_writes_current_in_legacy_shape(tmp_path: Path) -> None:
    current_file = tmp_path / "ow_records_current.json"
    current_file.write_text(
        json.dumps(
            {
                "this_file": {
                    "endpoint": "weather",
                    "fetched_at_utc": "2026-06-22T18:00:00Z",
                    "latency_ms": 288,
                },
                "data": {
                    "dt": 1782151200,
                    "id": 4180439,
                    "name": "Atlanta",
                    "timezone": -14400,
                    "coord": {"lat": 33.749, "lon": -84.388},
                    "visibility": 10000,
                    "sys": {"country": "US", "sunrise": 1782126350, "sunset": 1782178745},
                    "main": {
                        "temp": 87.8,
                        "feels_like": 93.2,
                        "temp_min": 84.0,
                        "temp_max": 89.1,
                        "pressure": 1015,
                        "humidity": 62,
                    },
                    "wind": {"speed": 2.57, "gust": 5.14, "deg": 210},
                    "clouds": {"all": 75},
                    "weather": [{"id": 803, "main": "Clouds", "description": "broken clouds", "icon": "04d"}],
                },
            }
        ),
        encoding="utf-8",
    )
    open_weather_collection = FakeCollection()
    ingest_runs_collection = FakeCollection()
    service = OpenWeatherMongoIngestService(
        open_weather_collection=open_weather_collection,
        ingestion_runs=MongoIngestionRunRepository(ingest_runs_collection),
    )

    result = service.ingest_current(current_file)

    assert result.status == "ok"
    query, update, upsert = open_weather_collection.update_calls[0]
    assert query == {
        "place_id": 4180439,
        "provider_endpoint": "weather",
        "observed_epoch_s": 1782151200,
    }
    assert upsert is True
    document = update["$set"]
    assert document["station_key"] == "openweather:4180439"
    assert document["place_name"] == "Atlanta"
    assert document["country"] == "US"
    assert document["norm"]["temp_c"]["temp"] == 87.8
    assert document["norm"]["pressure_hpa"]["station"] == 1015.0
    assert document["norm"]["weather"][0]["description"] == "broken clouds"


def test_openweather_mongo_ingest_writes_forecast_in_legacy_shape(tmp_path: Path) -> None:
    forecast_file = tmp_path / "ow_records_forecast.json"
    forecast_file.write_text(
        json.dumps(
            {
                "this_file": {
                    "endpoint": "forecast",
                    "fetched_at_utc": "2026-06-22T18:00:00Z",
                    "latency_ms": 212,
                },
                "data": {
                    "city": {
                        "id": 4180439,
                        "name": "Atlanta",
                        "country": "US",
                        "timezone": -14400,
                        "coord": {"lat": 33.749, "lon": -84.388},
                    },
                    "list": [
                        {
                            "dt": 1782162000,
                            "dt_txt": "2026-06-22 21:00:00",
                            "main": {
                                "temp": 84.2,
                                "feels_like": 88.0,
                                "temp_min": 82.7,
                                "temp_max": 84.2,
                                "pressure": 1016,
                                "humidity": 68,
                            },
                            "wind": {"speed": 3.1, "deg": 195},
                            "clouds": {"all": 92},
                            "pop": 0.35,
                            "rain": {"3h": 1.2},
                            "weather": [
                                {"id": 500, "main": "Rain", "description": "light rain", "icon": "10n"}
                            ],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    open_weather_collection = FakeCollection()
    ingest_runs_collection = FakeCollection()
    service = OpenWeatherMongoIngestService(
        open_weather_collection=open_weather_collection,
        ingestion_runs=MongoIngestionRunRepository(ingest_runs_collection),
    )

    result = service.ingest_forecast(forecast_file)

    assert result.status == "ok"
    query, update, upsert = open_weather_collection.update_calls[0]
    assert query == {
        "place_id": 4180439,
        "provider_endpoint": "forecast",
        "observed_epoch_s": 1782162000,
    }
    assert upsert is True
    document = update["$set"]
    assert document["station_key"] == "openweather:4180439"
    assert document["forecast_text_local"] == "2026-06-22 21:00:00"
    assert document["norm"]["pop"] == 0.35
    assert document["norm"]["precip_mm"]["rain_3h"] == 1.2
    assert document["norm"]["weather"][0]["main"] == "Rain"
