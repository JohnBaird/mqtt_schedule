from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from mqtt_schedule.mongo import MongoDatabase
from mqtt_schedule.mongo_ingestion import IngestionRunRecord, MongoIngestionRunRepository
from mqtt_schedule.settings import RuntimeSettings


class FakeCollection:
    def __init__(self) -> None:
        self.index_calls: list[tuple[list[tuple[str, int]], str, bool]] = []
        self.update_calls: list[tuple[dict, dict, bool]] = []
        self.find_one_result = None

    def create_index(self, keys, *, name, unique=False):
        self.index_calls.append((list(keys), name, unique))

    def update_one(self, query, update, upsert=False):
        self.update_calls.append((query, update, upsert))

    def find_one(self, query):
        return self.find_one_result


class FakeDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


class FakeAdmin:
    def command(self, name: str) -> None:
        if name != "ping":
            raise AssertionError(name)


class FakeClient:
    def __init__(self) -> None:
        self.admin = FakeAdmin()
        self.databases: dict[str, FakeDatabase] = {}
        self.closed = False

    def __getitem__(self, name: str) -> FakeDatabase:
        if name not in self.databases:
            self.databases[name] = FakeDatabase()
        return self.databases[name]

    def close(self) -> None:
        self.closed = True


def _settings(tmp_path: Path, **overrides) -> RuntimeSettings:
    base = dict(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
    )
    base.update(overrides)
    return RuntimeSettings(**base)


def test_mongo_database_builds_authenticated_uri(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        mongo_uri="mongodb://127.0.0.1:27017",
        mongo_db="homeWeather",
        mongo_authenticate=True,
        mongo_username="john",
        mongo_password="secret",
    )

    database = MongoDatabase(settings, client=FakeClient())

    assert database._build_mongo_uri() == "mongodb://john:secret@127.0.0.1:27017"


def test_mongo_database_keeps_existing_credentials_in_uri(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        mongo_uri="mongodb://user:pass@127.0.0.1:27017",
        mongo_db="homeWeather",
        mongo_authenticate=True,
        mongo_username="ignored",
        mongo_password="ignored",
    )

    database = MongoDatabase(settings, client=FakeClient())

    assert database._build_mongo_uri() == "mongodb://user:pass@127.0.0.1:27017"


def test_mongo_database_ensures_legacy_indexes(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        mongo_uri="mongodb://127.0.0.1:27017",
        mongo_db="homeWeather",
    )
    client = FakeClient()
    database = MongoDatabase(settings, client=client)

    database.ensure_indexes()

    db = client["homeWeather"]
    assert [call[1] for call in db["tempest_flow"].index_calls] == [
        "uq_station_epoch",
        "ix_station_observed_desc",
        "ix_stationkey_observed_desc",
    ]
    assert [call[1] for call in db["open_weather"].index_calls] == [
        "uq_place_endpoint_epoch",
        "ix_place_observed_desc",
        "ix_stationkey_observed_desc",
    ]
    assert [call[1] for call in db["stations"].index_calls] == [
        "uq_station_id",
        "ix_device_serial",
    ]
    assert [call[1] for call in db["ingestion_runs"].index_calls] == [
        "uq_source_filehash",
        "ix_ingested_desc",
        "ix_run_id",
    ]


def test_ingestion_run_repository_hashes_file_and_upserts_legacy_shape(tmp_path: Path) -> None:
    payload_file = tmp_path / "ow_records_current.json"
    payload_file.write_text('{"records": []}', encoding="utf-8")
    collection = FakeCollection()
    repository = MongoIngestionRunRepository(collection)
    now_utc = datetime(2026, 6, 22, 18, 0, tzinfo=timezone.utc)

    file_hash = repository.read_file_hash(payload_file)
    repository.upsert_record(
        IngestionRunRecord(
            run_id="run-1",
            source="open_weather:current",
            file_path=str(payload_file),
            file_hash=file_hash,
            status="ok",
            inserted=1,
            updated=2,
            skipped=3,
            error=None,
            ingested_at_utc=now_utc,
        )
    )

    assert len(collection.update_calls) == 1
    query, update, upsert = collection.update_calls[0]
    assert query == {"source": "open_weather:current", "file_hash": file_hash}
    assert upsert is True
    document = update["$setOnInsert"]
    assert document["run_id"] == "run-1"
    assert document["status"] == "ok"
    assert document["counts"] == {"inserted": 1, "updated": 2, "skipped": 3}
    assert document["ingested_at_utc"] == now_utc
