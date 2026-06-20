from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import getnode


@dataclass(frozen=True)
class DeviceIdentitySettings:
    serial_file: Path
    source_serial_override: str | None = None


class DeviceIdentity:
    def __init__(self, settings: DeviceIdentitySettings) -> None:
        self.settings = settings

    def get_source_serial(self) -> str:
        if self.settings.source_serial_override:
            return self._validate_serial(self.settings.source_serial_override.strip())

        existing = self._read_existing_serial()
        if existing is not None:
            return existing

        serial = self._derive_serial_from_mac()
        self._persist_serial(serial)
        return serial

    def _read_existing_serial(self) -> str | None:
        path = self.settings.serial_file
        if not path.exists():
            return None

        value = path.read_text(encoding="utf-8").strip()
        if not value:
            return None
        return self._validate_serial(value)

    def _persist_serial(self, serial: str) -> None:
        path = self.settings.serial_file
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            handle.write(serial)
            temp_name = handle.name
        os.replace(temp_name, path)

    @staticmethod
    def _derive_serial_from_mac() -> str:
        mac_int = int(getnode())
        return str(mac_int)

    @staticmethod
    def _validate_serial(value: str) -> str:
        if not value.isdigit():
            raise ValueError(f"Invalid device serial: {value!r}")
        return value
