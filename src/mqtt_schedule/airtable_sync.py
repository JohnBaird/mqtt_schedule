from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .settings import RuntimeSettings


@dataclass(frozen=True)
class AirtableSyncTarget:
    file_kind: str
    table_name: str
    output_path: Path


@dataclass(frozen=True)
class AirtableSyncFileResult:
    file_kind: str
    table_name: str
    output_path: Path
    record_count: int
    action: str


class AirtableSyncService:
    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        session: requests.sessions.Session | None = None,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.logger = logging.getLogger("mqtt_schedule.airtable_sync")

    def is_configured(self) -> bool:
        return bool(
            self.settings.airtable_base_url
            and self.settings.airtable_base_id
            and self.settings.airtable_api_key
        )

    def sync_all(self) -> list[AirtableSyncFileResult]:
        if not self.is_configured():
            raise RuntimeError("Airtable sync is not configured.")

        results: list[AirtableSyncFileResult] = []
        for target in self.targets():
            payload = self._fetch_table_payload(target.table_name)
            record_count = len(payload.get("records", []))
            action = _write_json_if_changed(target.output_path, payload)
            self.logger.info(
                "airtable_sync_complete file_kind=%s table_name=%s output_path=%s record_count=%s action=%s",
                target.file_kind,
                target.table_name,
                target.output_path,
                record_count,
                action,
            )
            results.append(
                AirtableSyncFileResult(
                    file_kind=target.file_kind,
                    table_name=target.table_name,
                    output_path=target.output_path,
                    record_count=record_count,
                    action=action,
                )
            )
        return results

    def targets(self) -> list[AirtableSyncTarget]:
        return [
            AirtableSyncTarget(
                file_kind="controller",
                table_name=self.settings.airtable_controller_table,
                output_path=self.settings.controller_file,
            ),
            AirtableSyncTarget(
                file_kind="schedule",
                table_name=self.settings.airtable_schedule_table,
                output_path=self.settings.schedule_file,
            ),
            AirtableSyncTarget(
                file_kind="access_users",
                table_name=self.settings.airtable_access_users_table,
                output_path=self.settings.access_users_file,
            ),
        ]

    def required_files_missing(self) -> list[Path]:
        return [target.output_path for target in self.targets() if not target.output_path.exists()]

    def _fetch_table_payload(self, table_name: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.settings.airtable_api_key}"}
        base_url = self.settings.airtable_base_url.rstrip("/")
        url = f"{base_url}/{self.settings.airtable_base_id}/{table_name}"
        records: list[dict[str, Any]] = []
        offset: str | None = None

        while True:
            params: dict[str, str] = {}
            if offset:
                params["offset"] = offset
            response = self.session.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            page_records = payload.get("records", [])
            if isinstance(page_records, list):
                records.extend(item for item in page_records if isinstance(item, dict))
            offset = payload.get("offset") if isinstance(payload.get("offset"), str) else None
            if not offset:
                break

        return {"records": records}


def _write_json_if_changed(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        current = None
    except json.JSONDecodeError:
        current = None

    if current == payload:
        return "unchanged"

    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(_normalized_json(payload), encoding="utf-8")
    temp_path.replace(path)
    return "created" if current is None else "updated"


def _normalized_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
