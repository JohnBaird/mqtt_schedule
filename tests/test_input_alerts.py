from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest
import requests

from mqtt_schedule import cli
from mqtt_schedule.airtable_backup import restore_missing_airtable_files, save_airtable_backups
from mqtt_schedule.airtable_sync import AirtableSyncService
from mqtt_schedule.airtable_repositories import FileControllerRepository, FileScheduleRepository
from mqtt_schedule.access_control import FileAccessUserRepository
from mqtt_schedule.input_alerts import FileInputAlertRepository, validate_input_alerts_file, validate_input_alerts_payload
from mqtt_schedule.settings import RuntimeSettings


@pytest.fixture
def settings(tmp_path):
    value = RuntimeSettings(
        schedule_file=tmp_path / "schedule.json", controller_file=tmp_path / "controllers.json",
        access_users_file=tmp_path / "users.json", clients_sysinfo_dir=tmp_path / "sysinfo",
        openweather_current_file=tmp_path / "current.json", openweather_forecast_file=tmp_path / "forecast.json",
        tempest_data_dir=tmp_path / "tempest", device_serial_file=tmp_path / "serial.txt",
        input_alerts_file=tmp_path / "airtable_input_alerts.json", airtable_backup_dir=tmp_path / "backup",
        airtable_base_id="app-test", airtable_api_key="test-only-pat", airtable_sync_seconds=0,
    )
    value.controller_file.write_text(json.dumps({"records": [{
        "id": "recController", "fields": {"Name": "Test Controller", "nameLink": "111", "enabled": True},
    }]}), encoding="utf-8")
    return value


def alert(*, record_id="recAlert", enabled=True, **changes):
    fields = {"Name": "Input 0 negative", "enabled": enabled, "controller": ["recController"],
              "inputCategory": "Digital GPIO", "inputIndex": 0, "edge": "negative",
              "channels": ["sms", "email"], "message": "Input 0 changed"}
    fields.update(changes)
    return {"id": record_id, "fields": fields}


def payload(*records):
    return {"records": list(records)}


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        pass

    def json(self):
        return self.value


class FakeSession:
    def __init__(self, tables):
        self.tables = {name: iter(pages) for name, pages in tables.items()}
        self.calls = []

    def get(self, url, *, headers, params, timeout):
        name = url.rsplit("/", 1)[-1]
        self.calls.append((name, params.get("offset")))
        value = next(self.tables[name])
        if isinstance(value, Exception):
            raise value
        return FakeResponse(value)


def validate(settings, value):
    return validate_input_alerts_payload(value, controller_file=settings.controller_file, path=settings.input_alerts_file)


def test_enabled_rules_resolve_controller_link_and_keep_both_directions(settings):
    value = payload(alert(inputIndex=0.0), alert(record_id="recPositive", edge="positive"),
                    {"id": "recDisabled", "fields": {"Name": "Incomplete disabled rule"}})
    settings.input_alerts_file.write_text(json.dumps(value), encoding="utf-8")
    summary = validate_input_alerts_file(settings.input_alerts_file, controller_file=settings.controller_file)
    assert summary.ok
    assert summary.record_count == 3
    assert summary.valid_count == 2
    rules = FileInputAlertRepository(settings.input_alerts_file, controller_file=settings.controller_file).list_rules()
    assert [rule.edge for rule in rules] == ["negative", "positive"]
    assert rules[0].controller_serial == "111"
    assert rules[0].controller_name == "Test Controller"
    assert rules[0].input_index == 0
    assert rules[0].channels == ("sms", "email")


@pytest.mark.parametrize("changes", [
    {"Name": ""}, {"inputCategory": ""}, {"message": ""},
    {"controller": []}, {"controller": ["111"]}, {"controller": ["recController", "recOther"]},
    {"inputIndex": -1}, {"inputIndex": 8}, {"inputIndex": True}, {"inputIndex": "0"}, {"inputIndex": 0.5},
    {"edge": "rising"}, {"channels": "sms"}, {"channels": ["push"]},
])
def test_invalid_enabled_rule_is_rejected(settings, changes):
    summary = validate(settings, payload(alert(**changes)))
    assert not summary.ok
    assert summary.valid_count == 0


@pytest.mark.parametrize("raw_enabled,expected", [
    (True, True), (False, False), ("true", True), (" TRUE ", True),
    ("false", False), (" FALSE ", False), (None, False), ("", False),
    ("yes", False), ("1", False), (1, False), (0, False), ([], False), ({}, False),
])
def test_all_airtable_tables_follow_same_enabled_convention(settings, raw_enabled, expected):
    controllers = json.loads(settings.controller_file.read_text(encoding="utf-8"))
    controllers["records"][0]["fields"]["enabled"] = raw_enabled
    settings.controller_file.write_text(json.dumps(controllers), encoding="utf-8")
    settings.schedule_file.write_text(json.dumps(payload({"id": "recSchedule", "fields": {
        "enabled": raw_enabled, "zoneNumber": ["Zone-1"],
    }})), encoding="utf-8")
    settings.access_users_file.write_text(json.dumps(payload({"id": "recUser", "fields": {
        "enabled": raw_enabled, "firstName": "Example", "pinNumber": "test-pin",
    }})), encoding="utf-8")
    settings.input_alerts_file.write_text(json.dumps(payload(alert(enabled=raw_enabled))), encoding="utf-8")

    assert FileControllerRepository(settings.controller_file).list_controllers()[0].enabled is expected
    assert FileScheduleRepository(settings.schedule_file).list_schedules()[0].enabled is expected
    user = FileAccessUserRepository(settings.access_users_file).find_enabled_user_by_credential("test-pin")
    assert (user is not None) is expected
    summary = validate_input_alerts_file(settings.input_alerts_file, controller_file=settings.controller_file)
    assert summary.ok
    assert summary.valid_count == int(expected)
    rules = FileInputAlertRepository(settings.input_alerts_file, controller_file=settings.controller_file).list_rules()
    assert len(rules) == int(expected)


def test_input_alert_example_follows_existing_disabled_reference_records():
    examples = Path(__file__).resolve().parent.parent / "deploy/examples"
    summary = validate_input_alerts_file(examples / "airtable_input_alerts.example.json",
                                         controller_file=examples / "airtable_config_data.example.json")
    assert summary.ok
    assert summary.record_count == 1
    assert summary.valid_count == 0


@pytest.mark.parametrize("value", [None, [], {}, {"records": {}}, payload(None),
                                   {"records": [{"id": "recInvalid", "fields": []}]},
                                   {"records": [{"fields": {}}]}])
def test_invalid_export_shape_is_rejected(settings, value):
    assert not validate(settings, value).ok


def test_duplicate_enabled_rule_is_rejected_but_empty_channels_are_valid(settings):
    assert not validate(settings, payload(alert(), alert(record_id="recDuplicate"))).ok
    assert not validate(settings, payload(alert(), alert())).ok
    assert validate(settings, payload(alert(channels=[]))).ok


def test_disabled_and_empty_exports_do_not_require_a_controller_cache(settings):
    settings = replace(settings, controller_file=settings.controller_file.parent / "missing.json")
    assert validate(settings, payload()).ok
    assert validate(settings, payload({"id": "recDisabled", "fields": {}})).ok
    assert not validate(settings, payload(alert())).ok


def test_rules_linked_to_disabled_controllers_are_valid_data_not_permission_to_send(settings):
    controllers = json.loads(settings.controller_file.read_text())
    controllers["records"][0]["fields"]["enabled"] = False
    settings.controller_file.write_text(json.dumps(controllers), encoding="utf-8")
    assert validate(settings, payload(alert())).ok


def test_manual_sync_downloads_only_alerts_with_zero_interval_and_optional_sync_off(settings):
    session = FakeSession({"input-alerts": [payload(alert(enabled=False))]})
    service = AirtableSyncService(settings, session=session)
    assert [target.file_kind for target in service.targets()] == ["controller", "schedule", "access_users"]
    result = service.sync_targets({"input_alerts"})[0]
    assert session.calls == [("input-alerts", None)]
    assert result.action == "created"
    assert result.record_count == 1
    assert json.loads(settings.input_alerts_file.read_text())["records"][0]["fields"]["enabled"] is False
    assert not settings.schedule_file.exists()
    assert not settings.access_users_file.exists()


def test_optional_sync_all_fetches_controller_before_resolving_new_alert_link(settings):
    settings = replace(settings, airtable_input_alerts_sync_enabled=True)
    controller = {"id": "recNewController", "fields": {"Name": "New", "nameLink": "222", "enabled": True}}
    session = FakeSession({"irrigation-config": [payload(controller)], "irrigation-schedule": [payload()],
                           "access-users": [payload()], "input-alerts": [payload(alert(controller=["recNewController"]))]})
    results = AirtableSyncService(settings, session=session).sync_all()
    assert [result.file_kind for result in results] == ["controller", "schedule", "access_users", "input_alerts"]
    assert FileInputAlertRepository(settings.input_alerts_file, controller_file=settings.controller_file).list_rules()[0].controller_serial == "222"


def test_missing_optional_alerts_file_never_becomes_required(settings):
    settings = replace(settings, airtable_input_alerts_sync_enabled=True)
    settings.schedule_file.write_text(json.dumps(payload()), encoding="utf-8")
    settings.access_users_file.write_text(json.dumps(payload()), encoding="utf-8")
    assert AirtableSyncService(settings).required_files_missing() == []


@pytest.mark.parametrize("candidate", [payload(alert(inputIndex=9)), {"records": "bad"}, {}, payload("bad-record")])
def test_bad_download_never_replaces_good_alert_export(settings, candidate):
    original = json.dumps(payload(alert())).encode()
    settings.input_alerts_file.write_bytes(original)
    service = AirtableSyncService(settings, session=FakeSession({"input-alerts": [candidate]}))
    with pytest.raises(ValueError):
        service.sync_targets({"input_alerts"})
    assert settings.input_alerts_file.read_bytes() == original


def test_paginated_alert_download_is_complete_and_identical_sync_does_not_rewrite(settings):
    first, second = alert(), alert(record_id="recSecond", edge="positive")
    session = FakeSession({"input-alerts": [{"records": [first], "offset": "page2"}, payload(second)]})
    service = AirtableSyncService(settings, session=session)
    assert service.sync_targets({"input_alerts"})[0].record_count == 2
    original_mtime = settings.input_alerts_file.stat().st_mtime_ns
    same = FakeSession({"input-alerts": [payload(first, second)]})
    assert AirtableSyncService(settings, session=same).sync_targets({"input_alerts"})[0].action == "unchanged"
    assert settings.input_alerts_file.stat().st_mtime_ns == original_mtime
    assert session.calls == [("input-alerts", None), ("input-alerts", "page2")]


@pytest.mark.parametrize("final_page", [requests.ConnectionError("offline"), {"records": [], "offset": "page2"}])
def test_failed_or_repeating_final_page_keeps_old_file_and_bounds_requests(settings, final_page):
    original = json.dumps(payload(alert())).encode()
    settings.input_alerts_file.write_bytes(original)
    session = FakeSession({"input-alerts": [{"records": [alert()], "offset": "page2"}, final_page]})
    with pytest.raises((requests.RequestException, ValueError)):
        AirtableSyncService(settings, session=session).sync_targets({"input_alerts"})
    assert settings.input_alerts_file.read_bytes() == original
    assert len(session.calls) == 2


def test_complete_empty_export_removes_rules(settings):
    settings.input_alerts_file.write_text(json.dumps(payload(alert())), encoding="utf-8")
    AirtableSyncService(settings, session=FakeSession({"input-alerts": [payload()]})).sync_targets({"input_alerts"})
    assert FileInputAlertRepository(settings.input_alerts_file, controller_file=settings.controller_file).list_rules() == []


def test_alert_backup_is_validated_and_restored(settings):
    original = json.dumps(payload(alert())).encode()
    settings.input_alerts_file.write_bytes(original)
    save_airtable_backups(settings)
    backup = settings.airtable_backup_dir / "airtable_input_alerts.json"
    assert backup.read_bytes() == original
    settings.input_alerts_file.write_text(json.dumps(payload(alert(edge="bad"))), encoding="utf-8")
    save_airtable_backups(settings)
    assert backup.read_bytes() == original
    restored = replace(settings, input_alerts_file=settings.input_alerts_file.parent / "restored.json")
    restore_missing_airtable_files(restored)
    assert restored.input_alerts_file.read_bytes() == original


def test_cli_manual_download_and_validation_never_start_mqtt_or_notifications(settings, monkeypatch, capsys):
    session = FakeSession({"input-alerts": [payload(alert(enabled=False))]})
    service = AirtableSyncService(settings, session=session)
    monkeypatch.setattr(cli.RuntimeSettings, "from_env", staticmethod(lambda: settings))
    monkeypatch.setattr(cli, "AirtableSyncService", lambda _: service)

    def forbidden(*args, **kwargs):
        pytest.fail("A rules-only command must not initialize the running service")

    monkeypatch.setattr(cli, "_ensure_required_airtable_files", forbidden)
    monkeypatch.setattr(cli, "build_sms_notifications", forbidden)
    monkeypatch.setattr(cli, "build_email_notifications", forbidden)
    monkeypatch.setattr(cli.PahoClientFactory, "connect", forbidden)
    monkeypatch.setattr(sys, "argv", ["mqtt_schedule", "--sync-input-alerts-now"])
    assert cli.main() == 0
    assert "record_count=1 action=created" in capsys.readouterr().out
    assert (settings.airtable_backup_dir / "airtable_input_alerts.json").exists()
    monkeypatch.setattr(sys, "argv", ["mqtt_schedule", "--validate-input-alerts"])
    assert cli.main() == 0
    assert "enabled_rules=0 ok=true" in capsys.readouterr().out
    assert session.calls == [("input-alerts", None)]


def test_manual_api_failure_is_visible_and_does_not_log_credentials(settings, monkeypatch, caplog):
    response = requests.Response()
    response.status_code = 403
    error = requests.HTTPError("test-only-pat", response=response)
    service = AirtableSyncService(settings, session=FakeSession({"input-alerts": [error]}))
    monkeypatch.setattr(cli, "AirtableSyncService", lambda _: service)
    assert cli._sync_input_alerts_now(settings) == 1
    assert "http_status=403" in caplog.text
    assert "test-only-pat" not in caplog.text


def test_validate_missing_alert_file_returns_failure_without_network(settings):
    assert cli._validate_input_alerts(settings) == 1


def test_periodic_alert_sync_is_opt_in_and_zero_interval_still_disables_it(settings, monkeypatch):
    session = FakeSession({"input-alerts": [payload(alert(enabled=False))]})
    service = AirtableSyncService(settings, session=session)
    monkeypatch.setattr(cli, "AirtableSyncService", lambda _: service)
    assert cli.build_airtable_sync_jobs(settings=settings) == []
    enabled = replace(settings, airtable_input_alerts_sync_enabled=True,
                      airtable_input_alerts_sync_run_immediately=True, airtable_sync_seconds=0)
    assert cli.build_airtable_sync_jobs(settings=enabled) == []
    enabled = replace(enabled, airtable_sync_seconds=86400)
    jobs = cli.build_airtable_sync_jobs(settings=enabled)
    assert [job.job_id for job in jobs][-1] == "airtable-sync-input-alerts"
    assert jobs[-1].run_immediately is True
    jobs[-1].fn()
    assert session.calls == [("input-alerts", None)]


def test_conflicting_sync_commands_are_rejected(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["mqtt_schedule", "--sync-airtable-now", "--sync-input-alerts-now"])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 2


def test_input_alert_settings_load_from_json_and_environment(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parent.parent / "deploy/runtime.example.json"
    config = json.loads(source.read_text(encoding="utf-8"))
    config.update({"input_alerts_file": str(tmp_path / "rules.json"), "airtable_input_alerts_table": "site-alerts",
                   "airtable_input_alerts_sync_enabled": True, "airtable_input_alerts_sync_run_immediately": True})
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    value = RuntimeSettings.from_json_file(path)
    assert value.input_alerts_file == tmp_path / "rules.json"
    assert value.airtable_input_alerts_table == "site-alerts"
    assert value.airtable_input_alerts_sync_enabled is True
    assert value.airtable_input_alerts_sync_run_immediately is True
    monkeypatch.setenv("MQTT_SCHEDULE_INPUT_ALERTS_FILE", str(tmp_path / "override.json"))
    monkeypatch.setenv("MQTT_SCHEDULE_AIRTABLE_INPUT_ALERTS_TABLE", "override-alerts")
    monkeypatch.setenv("MQTT_SCHEDULE_AIRTABLE_INPUT_ALERTS_SYNC_ENABLED", "false")
    monkeypatch.setenv("MQTT_SCHEDULE_AIRTABLE_INPUT_ALERTS_SYNC_RUN_IMMEDIATELY", "false")
    value = RuntimeSettings.from_json_file(path)
    assert value.input_alerts_file == tmp_path / "override.json"
    assert value.airtable_input_alerts_table == "override-alerts"
    assert value.airtable_input_alerts_sync_enabled is False
    assert value.airtable_input_alerts_sync_run_immediately is False
    assert RuntimeSettings.from_env().input_alerts_file == tmp_path / "override.json"
