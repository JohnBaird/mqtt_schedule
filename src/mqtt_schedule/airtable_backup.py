from __future__ import annotations

import logging
import os
from pathlib import Path

from .airtable_repositories import (
    validate_access_users_file,
    validate_controller_file,
    validate_schedule_file,
)
from .settings import RuntimeSettings


_LOGGER = logging.getLogger("mqtt_schedule.airtable_backup")


def _live_files(settings: RuntimeSettings):
    return (
        ("schedule", settings.schedule_file, "airtable_schedule_data.json", validate_schedule_file),
        ("controller", settings.controller_file, "airtable_config_data.json", validate_controller_file),
        ("access_users", settings.access_users_file, "airtable_access_users.json", validate_access_users_file),
    )


def save_airtable_backups(settings: RuntimeSettings) -> None:
    """Keep private last-known-good copies of existing Airtable exports."""
    for kind, live_path, backup_name, validate in _live_files(settings):
        if not live_path.exists():
            continue
        summary = validate(live_path)
        if not summary.ok:
            _LOGGER.warning("airtable_backup_skipped kind=%s reason=invalid_live_file path=%s", kind, live_path)
            continue
        backup_path = settings.airtable_backup_dir / backup_name
        _copy_if_changed(live_path, backup_path, private=True)
        _LOGGER.info("airtable_backup_saved kind=%s path=%s", kind, backup_path)


def restore_missing_airtable_files(settings: RuntimeSettings) -> None:
    """Restore only missing live files from validated private copies."""
    for kind, live_path, backup_name, validate in _live_files(settings):
        if live_path.exists():
            continue
        backup_path = settings.airtable_backup_dir / backup_name
        if not backup_path.exists():
            continue
        summary = validate(backup_path)
        if not summary.ok:
            _LOGGER.warning("airtable_backup_ignored kind=%s reason=invalid_backup path=%s", kind, backup_path)
            continue
        _copy_if_changed(backup_path, live_path, private=False)
        _LOGGER.warning("airtable_backup_restored kind=%s source=%s destination=%s", kind, backup_path, live_path)


def _copy_if_changed(source: Path, destination: Path, *, private: bool) -> None:
    payload = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if private:
        os.chmod(destination.parent, 0o700)
    try:
        if destination.read_bytes() == payload:
            if private:
                os.chmod(destination, 0o600)
            return
    except FileNotFoundError:
        pass
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if private:
        temporary.touch(mode=0o600, exist_ok=True)
        os.chmod(temporary, 0o600)
    temporary.write_bytes(payload)
    temporary.replace(destination)
