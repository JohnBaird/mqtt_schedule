from __future__ import annotations

import json
from pathlib import Path

from mqtt_schedule.mongo_ingestion import MongoIngestionRunRepository
from mqtt_schedule.mongo_tempest import TempestMongoIngestService


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


def test_tempest_mongo_ingest_writes_station_meta_in_legacy_shape(tmp_path: Path) -> None:
    meta_file = tmp_path / "station_meta.json"
    meta_file.write_text(
        json.dumps(
            {
                "stations": [
                    {
                        "station_id": 201749,
                        "timezone": "America/New_York",
                        "latitude": 33.3,
                        "longitude": -84.4,
                        "public_name": "150Woodbridge",
                        "name": "Back Yard",
                        "location_id": 77,
                        "devices": [{"serial_number": "ABC123"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    stations_collection = FakeCollection()
    ingest_runs_collection = FakeCollection()
    service = TempestMongoIngestService(
        stations_collection=stations_collection,
        tempest_flow_collection=FakeCollection(),
        ingestion_runs=MongoIngestionRunRepository(ingest_runs_collection),
    )

    result = service.ingest_station_meta(meta_file)

    assert result.status == "ok"
    query, update, upsert = stations_collection.update_calls[0]
    assert query == {"station_id": 201749}
    assert upsert is True
    document = update["$set"]
    assert document["station_key"] == "tempest:201749"
    assert document["timezone"] == "America/New_York"
    assert document["public_name"] == "150Woodbridge"
    assert document["raw"]["devices"][0]["serial_number"] == "ABC123"


def test_tempest_mongo_ingest_writes_obs_norm_in_legacy_shape(tmp_path: Path) -> None:
    obs_file = tmp_path / "station_obs_201749.json"
    obs_file.write_text(
        json.dumps(
            {
                "station_id": 201749,
                "timezone": "America/New_York",
                "station_name": "Back Yard",
                "station_units": {
                    "units_temp": "c",
                    "units_pressure": "hpa",
                    "units_precip": "in",
                    "units_wind": "mph",
                },
                "obs": [
                    {
                        "timestamp": 1781963992,
                        "air_temperature": 30.0,
                        "relative_humidity": 55,
                        "precip": 0.1,
                        "precip_accum_last_1hr": 0.2,
                        "precip_accum_local_day": 0.3,
                        "precip_accum_local_yesterday_final": 0.4,
                        "wind_avg": 10.0,
                        "wind_gust": 12.0,
                        "wind_lull": 8.0,
                        "wind_direction": 270,
                        "solar_radiation": 800,
                        "uv": 6.2,
                        "brightness": 12000,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tempest_collection = FakeCollection()
    ingest_runs_collection = FakeCollection()
    service = TempestMongoIngestService(
        stations_collection=FakeCollection(),
        tempest_flow_collection=tempest_collection,
        ingestion_runs=MongoIngestionRunRepository(ingest_runs_collection),
    )

    result = service.ingest_station_obs(obs_file)

    assert result.status == "ok"
    query, update, upsert = tempest_collection.update_calls[0]
    assert query == {"station_id": 201749, "observed_epoch_s": 1781963992}
    assert upsert is True
    document = update["$set"]
    assert document["station_key"] == "tempest:201749"
    assert document["station_name"] == "Back Yard"
    assert round(document["norm"]["precip_mm"]["instant"], 2) == 2.54
    assert round(document["norm"]["wind"]["avg_mps"], 5) == 4.4704
    assert document["norm"]["wind"]["direction_deg"] == 270
    assert document["norm"]["solar_radiation_wm2"] == 800.0
    assert document["raw"]["timestamp"] == 1781963992


def test_tempest_mongo_ingest_directory_reads_current_files_only(tmp_path: Path) -> None:
    (tmp_path / "station_meta.json").write_text('{"stations": []}', encoding="utf-8")
    (tmp_path / "station_obs_201749.json").write_text(
        '{"station_id": 201749, "station_units": {}, "obs": [{"timestamp": 1781963992}]}',
        encoding="utf-8",
    )
    (tmp_path / "station_obs_201749_20260622.json").write_text(
        '{"station_id": 201749, "station_units": {}, "obs": [{"timestamp": 1781963993}]}',
        encoding="utf-8",
    )
    service = TempestMongoIngestService(
        stations_collection=FakeCollection(),
        tempest_flow_collection=FakeCollection(),
        ingestion_runs=MongoIngestionRunRepository(FakeCollection()),
    )

    results = service.ingest_directory(tmp_path)

    assert [result.source for result in results] == [
        "tempest_flow:station_meta",
        "tempest_flow:station_obs",
    ]
