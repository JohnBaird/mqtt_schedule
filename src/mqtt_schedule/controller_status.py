from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .csv_reporting import LegacyCsvRecorder


@dataclass(frozen=True)
class ControllerStatusUpdate:
    source_serial: str
    response: str | None
    reason: str | None
    seen_at: datetime
    config_sync_requested: bool = False


class ControllerStatusStore:
    def __init__(self, path: str | Path, *, csv_recorder: LegacyCsvRecorder | None = None) -> None:
        self.path = Path(path)
        self.csv_recorder = csv_recorder
        self.logger = logging.getLogger("mqtt_schedule.controller_status")

    def record_online_status(self, update: ControllerStatusUpdate) -> None:
        payload = self._load()
        controllers = payload.setdefault("controllers", {})
        controller = dict(controllers.get(update.source_serial) or {})
        seen_at = update.seen_at.isoformat()

        controller["last_seen_at"] = seen_at
        controller["last_response"] = update.response
        controller["last_reason"] = update.reason
        controller["online"] = update.response == "online"
        if update.reason == "restarted":
            controller["last_restart_at"] = seen_at
        if update.config_sync_requested:
            controller["last_config_sync_request_at"] = seen_at

        controllers[update.source_serial] = controller
        payload["updated_at"] = seen_at
        self._write(payload)
        self.logger.info(
            "controller_status_updated source_serial=%s response=%s reason=%s config_sync_requested=%s path=%s",
            update.source_serial,
            update.response,
            update.reason,
            update.config_sync_requested,
            self.path,
        )

    def refresh_online_flags(self, *, now: datetime, offline_after_seconds: int) -> None:
        payload = self._load()
        controllers = payload.setdefault("controllers", {})
        changed_serials: list[str] = []

        for source_serial, controller in controllers.items():
            if not isinstance(controller, dict):
                continue
            last_seen_at_raw = controller.get("last_seen_at")
            if not isinstance(last_seen_at_raw, str) or not last_seen_at_raw.strip():
                continue
            try:
                last_seen_at = datetime.fromisoformat(last_seen_at_raw)
            except ValueError:
                continue

            should_be_online = (now - last_seen_at).total_seconds() <= offline_after_seconds
            if controller.get("online") == should_be_online:
                continue

            controller["online"] = should_be_online
            if not should_be_online:
                controller["last_offline_at"] = now.isoformat()
                if self.csv_recorder is not None:
                    self.csv_recorder.record_controller_offline_event(
                        source_serial=source_serial,
                        last_seen_at=last_seen_at.isoformat(),
                        detected_at=now.isoformat(),
                        last_response=str(controller.get("last_response") or ""),
                        last_reason=str(controller.get("last_reason") or ""),
                        offline_after_seconds=offline_after_seconds,
                    )
            changed_serials.append(source_serial)

        if not changed_serials:
            return

        payload["updated_at"] = now.isoformat()
        self._write(payload)
        self.logger.info(
            "controller_status_refreshed changed_count=%s offline_after_seconds=%s controllers=%s path=%s",
            len(changed_serials),
            offline_after_seconds,
            ",".join(sorted(changed_serials)),
            self.path,
        )

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"controllers": {}}
        except json.JSONDecodeError:
            return {"controllers": {}}
        if not isinstance(raw, dict):
            return {"controllers": {}}
        if not isinstance(raw.get("controllers"), dict):
            raw["controllers"] = {}
        return raw

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp_path.replace(self.path)
