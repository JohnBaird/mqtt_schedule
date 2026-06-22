from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IngestionRunRecord:
    run_id: str
    source: str
    file_path: str
    file_hash: str
    status: str
    inserted: int
    updated: int
    skipped: int
    ingested_at_utc: datetime
    error: str | None = None


class MongoIngestionRunRepository:
    def __init__(self, collection: Any) -> None:
        self.collection = collection

    def find_existing(self, *, source: str, file_hash: str) -> dict[str, Any] | None:
        return self.collection.find_one({"source": source, "file_hash": file_hash})

    def upsert_record(self, record: IngestionRunRecord) -> None:
        self.collection.update_one(
            {"source": record.source, "file_hash": record.file_hash},
            {"$setOnInsert": self._document(record)},
            upsert=True,
        )

    @staticmethod
    def read_file_hash(path: str | Path) -> str:
        payload = Path(path).read_bytes()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _document(record: IngestionRunRecord) -> dict[str, Any]:
        return {
            "run_id": record.run_id,
            "source": record.source,
            "file_path": record.file_path,
            "file_hash": record.file_hash,
            "status": record.status,
            "counts": {
                "inserted": int(record.inserted),
                "updated": int(record.updated),
                "skipped": int(record.skipped),
            },
            "error": record.error,
            "ingested_at_utc": record.ingested_at_utc,
        }
