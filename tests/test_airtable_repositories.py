from pathlib import Path

from mqtt_schedule.airtable_repositories import FileControllerRepository, FileScheduleRepository


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
