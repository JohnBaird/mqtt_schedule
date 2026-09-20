import json
from pathlib import Path

import pytest

from mqtt_schedule.cli import _ensure_required_airtable_files
from mqtt_schedule.settings import RuntimeSettings


EXAMPLES = Path(__file__).resolve().parent.parent / "deploy" / "examples"


def _settings(tmp_path: Path) -> RuntimeSettings:
    return RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "sysinfo",
        openweather_current_file=tmp_path / "weather.json",
        openweather_forecast_file=tmp_path / "forecast.json",
        tempest_data_dir=tmp_path / "tempest",
        device_serial_file=tmp_path / "serial.txt",
        airtable_backup_dir=tmp_path / "private_backup",
    )


def _write_examples(settings: RuntimeSettings) -> None:
    for path in (settings.schedule_file, settings.controller_file, settings.access_users_file):
        source = EXAMPLES / path.name.replace(".json", ".example.json")
        path.write_bytes(source.read_bytes())


def test_existing_exports_create_backups_and_missing_file_is_restored(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_examples(settings)
    original_controller = settings.controller_file.read_bytes()

    _ensure_required_airtable_files(settings)
    assert (settings.airtable_backup_dir / settings.controller_file.name).read_bytes() == original_controller

    settings.controller_file.unlink()
    _ensure_required_airtable_files(settings)

    assert settings.controller_file.read_bytes() == original_controller
    assert json.loads(settings.controller_file.read_text(encoding="utf-8"))["records"][0]["fields"]["enabled"] is False


def test_failed_startup_sync_restores_missing_file_from_backup(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    _write_examples(settings)
    _ensure_required_airtable_files(settings)
    settings.schedule_file.unlink()

    class FailingSyncService:
        def __init__(self, _settings):
            self.settings = _settings

        def required_files_missing(self):
            return [self.settings.schedule_file]

        def is_configured(self):
            return True

        def sync_targets(self, file_kinds):
            raise ConnectionError("Airtable unavailable")

    monkeypatch.setattr("mqtt_schedule.cli.AirtableSyncService", FailingSyncService)
    _ensure_required_airtable_files(settings)
    assert settings.schedule_file.exists()


def test_missing_exports_without_sync_or_backup_fail(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(RuntimeError, match="Required Airtable files are missing"):
        _ensure_required_airtable_files(settings)


def test_invalid_live_export_does_not_replace_good_backup(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _write_examples(settings)
    _ensure_required_airtable_files(settings)
    backup = settings.airtable_backup_dir / settings.controller_file.name
    original_controller = backup.read_bytes()

    settings.controller_file.write_text("{invalid", encoding="utf-8")
    _ensure_required_airtable_files(settings)

    assert backup.read_bytes() == original_controller