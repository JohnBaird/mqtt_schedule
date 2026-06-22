from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient

from .settings import RuntimeSettings


@dataclass(frozen=True)
class MongoCollections:
    open_weather: Any
    tempest_flow: Any
    stations: Any
    ingestion_runs: Any


@dataclass(frozen=True)
class MongoIndexSpec:
    name: str
    keys: tuple[tuple[str, int], ...]
    unique: bool = False


class MongoDatabase:
    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        client: MongoClient | None = None,
    ) -> None:
        self.settings = settings
        self._external_client = client
        self._client = client
        self._database = None
        self.logger = logging.getLogger("mqtt_schedule.mongo")

    def is_configured(self) -> bool:
        return bool(self.settings.mongo_uri and self.settings.mongo_db)

    def connect(self) -> MongoClient:
        if not self.is_configured():
            raise RuntimeError("MongoDB is not configured.")
        if self._client is not None:
            if self._database is None:
                self._database = self._client[self.settings.mongo_db]
            return self._client

        uri = self._build_mongo_uri()
        self.logger.info(
            "mongo_connect_start mongo_db=%s auth=%s",
            self.settings.mongo_db,
            self.settings.mongo_authenticate,
        )
        self._client = MongoClient(
            uri,
            connectTimeoutMS=self.settings.mongo_connect_timeout_ms,
            serverSelectionTimeoutMS=self.settings.mongo_server_selection_timeout_ms,
        )
        self._client.admin.command("ping")
        self._database = self._client[self.settings.mongo_db]
        self.logger.info("mongo_connect_complete mongo_db=%s", self.settings.mongo_db)
        return self._client

    def close(self) -> None:
        if self._client is None or self._external_client is not None:
            return
        self._client.close()
        self.logger.info("mongo_client_closed")
        self._client = None
        self._database = None

    def collections(self) -> MongoCollections:
        if self._database is None:
            self.connect()
        assert self._database is not None
        return MongoCollections(
            open_weather=self._database[self.settings.mongo_col_open_weather],
            tempest_flow=self._database[self.settings.mongo_col_tempest_flow],
            stations=self._database[self.settings.mongo_col_stations],
            ingestion_runs=self._database[self.settings.mongo_col_ingestion_runs],
        )

    def ensure_indexes(self) -> None:
        collections = self.collections()
        self._ensure_collection_indexes(
            collections.tempest_flow,
            (
                MongoIndexSpec(
                    name="uq_station_epoch",
                    keys=(("station_id", ASCENDING), ("observed_epoch_s", ASCENDING)),
                    unique=True,
                ),
                MongoIndexSpec(
                    name="ix_station_observed_desc",
                    keys=(("station_id", ASCENDING), ("observed_at_utc", DESCENDING)),
                ),
                MongoIndexSpec(
                    name="ix_stationkey_observed_desc",
                    keys=(("station_key", ASCENDING), ("observed_at_utc", DESCENDING)),
                ),
            ),
        )
        self._ensure_collection_indexes(
            collections.open_weather,
            (
                MongoIndexSpec(
                    name="uq_place_endpoint_epoch",
                    keys=(
                        ("place_id", ASCENDING),
                        ("provider_endpoint", ASCENDING),
                        ("observed_epoch_s", ASCENDING),
                    ),
                    unique=True,
                ),
                MongoIndexSpec(
                    name="ix_place_observed_desc",
                    keys=(("place_id", ASCENDING), ("observed_at_utc", DESCENDING)),
                ),
                MongoIndexSpec(
                    name="ix_stationkey_observed_desc",
                    keys=(("station_key", ASCENDING), ("observed_at_utc", DESCENDING)),
                ),
            ),
        )
        self._ensure_collection_indexes(
            collections.stations,
            (
                MongoIndexSpec(
                    name="uq_station_id",
                    keys=(("station_id", ASCENDING),),
                    unique=True,
                ),
                MongoIndexSpec(
                    name="ix_device_serial",
                    keys=(("devices.serial_number", ASCENDING),),
                ),
            ),
        )
        self._ensure_collection_indexes(
            collections.ingestion_runs,
            (
                MongoIndexSpec(
                    name="uq_source_filehash",
                    keys=(("source", ASCENDING), ("file_hash", ASCENDING)),
                    unique=True,
                ),
                MongoIndexSpec(
                    name="ix_ingested_desc",
                    keys=(("ingested_at_utc", DESCENDING),),
                ),
                MongoIndexSpec(
                    name="ix_run_id",
                    keys=(("run_id", ASCENDING),),
                ),
            ),
        )
        self.logger.info("mongo_indexes_ensured")

    def _ensure_collection_indexes(
        self,
        collection: Any,
        specs: tuple[MongoIndexSpec, ...],
    ) -> None:
        for spec in specs:
            collection.create_index(list(spec.keys), name=spec.name, unique=spec.unique)

    def _build_mongo_uri(self) -> str:
        uri = (self.settings.mongo_uri or "").strip()
        if not uri.startswith("mongodb://") and not uri.startswith("mongodb+srv://"):
            raise ValueError("mongo_uri must start with mongodb:// or mongodb+srv://")
        if not self.settings.mongo_authenticate:
            return uri

        if self._uri_has_credentials(uri):
            return uri

        username = (self.settings.mongo_username or "").strip()
        password = (self.settings.mongo_password or "").strip()
        if not username or not password:
            raise ValueError("Mongo authentication is enabled but username/password are missing.")

        scheme, rest = uri.split("://", 1)
        return f"{scheme}://{username}:{password}@{rest}"

    @staticmethod
    def _uri_has_credentials(uri: str) -> bool:
        try:
            host_part = uri.split("://", 1)[1].split("/", 1)[0]
        except IndexError:
            return False
        return "@" in host_part
