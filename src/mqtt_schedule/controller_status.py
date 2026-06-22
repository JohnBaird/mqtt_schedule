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
        was_online = bool(controller.get("online", False))

        controller["last_seen_at"] = seen_at
        controller["last_response"] = update.response
        controller["last_reason"] = update.reason
        if update.response == "online":
            if was_online or "online" not in controller:
                controller["online"] = True
                controller.pop("recovery_started_at", None)
            else:
                controller["online"] = False
                controller.setdefault("recovery_started_at", seen_at)
        else:
            controller["online"] = False
            controller.pop("recovery_started_at", None)
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

    def refresh_online_flags(
        self,
        *,
        now: datetime,
        offline_after_seconds: int,
        online_recovery_after_seconds: int,
    ) -> None:
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

            is_fresh = (now - last_seen_at).total_seconds() <= offline_after_seconds
            currently_online = bool(controller.get("online", False))

            if currently_online and not is_fresh:
                controller["online"] = False
                controller["last_offline_at"] = now.isoformat()
                controller.pop("recovery_started_at", None)
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
                continue

            if currently_online or not is_fresh or controller.get("last_response") != "online":
                if not is_fresh:
                    controller.pop("recovery_started_at", None)
                continue

            recovery_started_at_raw = controller.get("recovery_started_at")
            if not isinstance(recovery_started_at_raw, str) or not recovery_started_at_raw.strip():
                controller["recovery_started_at"] = last_seen_at.isoformat()
                payload["updated_at"] = now.isoformat()
                self._write(payload)
                continue
            try:
                recovery_started_at = datetime.fromisoformat(recovery_started_at_raw)
            except ValueError:
                controller["recovery_started_at"] = last_seen_at.isoformat()
                payload["updated_at"] = now.isoformat()
                self._write(payload)
                continue

            if (now - recovery_started_at).total_seconds() < online_recovery_after_seconds:
                continue

            controller["online"] = True
            controller["last_online_recovered_at"] = now.isoformat()
            controller.pop("recovery_started_at", None)
            if self.csv_recorder is not None:
                self.csv_recorder.record_controller_online_recovered_event(
                    source_serial=source_serial,
                    last_seen_at=last_seen_at.isoformat(),
                    detected_at=now.isoformat(),
                    last_response=str(controller.get("last_response") or ""),
                    last_reason=str(controller.get("last_reason") or ""),
                    online_recovery_after_seconds=online_recovery_after_seconds,
                )
            changed_serials.append(source_serial)

        if not changed_serials:
            return

        payload["updated_at"] = now.isoformat()
        self._write(payload)
        self.logger.info(
            "controller_status_refreshed changed_count=%s offline_after_seconds=%s online_recovery_after_seconds=%s controllers=%s path=%s",
            len(changed_serials),
            offline_after_seconds,
            online_recovery_after_seconds,
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
