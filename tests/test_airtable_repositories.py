import json
from pathlib import Path

from mqtt_schedule.airtable_repositories import (
    FileControllerRepository,
    FileScheduleRepository,
    validate_controller_file,
    validate_schedule_file,
)


TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
LEGACY_CONFIG_DIR = REPO_ROOT / "tests" / "fixtures" / "legacy_config"


def test_reads_schedule_records_from_legacy_export() -> None:
    repo = FileScheduleRepository(LEGACY_CONFIG_DIR / "airtable_schedule_data.json")

    schedules = repo.list_schedules()

    assert schedules
    assert any(item.output_type == "output-irrigation" for item in schedules)
    assert any(item.zone_category == "Sunset" for item in schedules)


def test_reads_controller_records_from_legacy_export() -> None:
    repo = FileControllerRepository(LEGACY_CONFIG_DIR / "airtable_config_data.json")

    controllers = repo.list_controllers()

    assert controllers
    assert any(item.enabled for item in controllers)
    assert any(item.name_link == "242606363309393" for item in controllers)


def test_validate_legacy_schedule_export_ok() -> None:
    summary = validate_schedule_file(LEGACY_CONFIG_DIR / "airtable_schedule_data.json")

    assert summary.ok is True
    assert summary.record_count == 2
    assert summary.valid_count == 2


def test_validate_legacy_controller_export_ok() -> None:
    summary = validate_controller_file(LEGACY_CONFIG_DIR / "airtable_config_data.json")

    assert summary.ok is True
    assert summary.record_count == 1
    assert summary.valid_count == 1


def test_validate_schedule_file_reports_missing_records_key(tmp_path: Path) -> None:
    path = tmp_path / "airtable_schedule_data.json"
    path.write_text(json.dumps({"not_records": []}), encoding="utf-8")

    summary = validate_schedule_file(path)

    assert summary.ok is False
    assert any("missing the records key" in issue.message for issue in summary.issues)
