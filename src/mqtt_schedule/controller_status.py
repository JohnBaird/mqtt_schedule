from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ControllerStatusUpdate:
    source_serial: str
    response: str | None
    reason: str | None
    seen_at: datetime
    config_sync_requested: bool = False


class ControllerStatusStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
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
