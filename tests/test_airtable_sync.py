import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from mqtt_schedule.airtable_sync import AirtableSyncService
from mqtt_schedule.settings import RuntimeSettings


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payloads_by_table):
        self.payloads_by_table = payloads_by_table
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        table_name = url.rstrip("/").split("/")[-1]
        offset = None if params is None else params.get("offset")
        self.calls.append((table_name, offset))
        payloads = self.payloads_by_table[table_name]
        index = 0 if offset is None else 1
        return FakeResponse(payloads[index])


def _settings(tmp_path: Path) -> RuntimeSettings:
    return RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=tmp_path / "airtable_access_users.json",
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        airtable_base_id="app123",
        airtable_api_key="pat123",
    )


def test_airtable_sync_writes_all_required_files(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    session = FakeSession(
        {
            "irrigation-config": [{"records": [{"id": "rec-1", "fields": {"Name": "A", "nameLink": "111"}}]}],
            "irrigation-schedule": [{"records": [{"id": "rec-2", "fields": {"zoneNumber": ["Zone-1"]}}]}],
            "access-users": [{"records": [{"id": "rec-3", "fields": {"firstName": "John", "pinNumber": "123"}}]}],
        }
    )

    results = AirtableSyncService(settings, session=session).sync_all()

    assert [result.file_kind for result in results] == ["controller", "schedule", "access_users"]
    assert json.loads(settings.controller_file.read_text(encoding="utf-8"))["records"][0]["id"] == "rec-1"
    assert json.loads(settings.schedule_file.read_text(encoding="utf-8"))["records"][0]["id"] == "rec-2"
    assert json.loads(settings.access_users_file.read_text(encoding="utf-8"))["records"][0]["id"] == "rec-3"


def test_airtable_sync_skips_overwrite_when_payload_is_identical(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    controller_payload = {"records": [{"id": "rec-1", "fields": {"Name": "A", "nameLink": "111"}}]}
    settings.controller_file.write_text(json.dumps(controller_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    session = FakeSession(
        {
            "irrigation-config": [controller_payload],
            "irrigation-schedule": [{"records": []}],
            "access-users": [{"records": []}],
        }
    )

    results = AirtableSyncService(settings, session=session).sync_all()

    controller_result = next(result for result in results if result.file_kind == "controller")
    assert controller_result.action == "unchanged"


def test_airtable_sync_handles_pagination(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    session = FakeSession(
        {
            "irrigation-config": [
                {"records": [{"id": "rec-1", "fields": {"Name": "A", "nameLink": "111"}}], "offset": "next-page"},
                {"records": [{"id": "rec-2", "fields": {"Name": "B", "nameLink": "222"}}]},
            ],
            "irrigation-schedule": [{"records": []}],
            "access-users": [{"records": []}],
        }
    )

    AirtableSyncService(settings, session=session).sync_all()

    payload = json.loads(settings.controller_file.read_text(encoding="utf-8"))
    assert [item["id"] for item in payload["records"]] == ["rec-1", "rec-2"]
    assert ("irrigation-config", None) in session.calls
    assert ("irrigation-config", "next-page") in session.calls


def test_airtable_sync_targets_only_requested_export(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    session = FakeSession({
        "irrigation-config": [{"records": [{"id": "rec-1", "fields": {"Name": "A", "nameLink": "111"}}]}],
    })

    results = AirtableSyncService(settings, session=session).sync_targets({"controller"})

    assert [result.file_kind for result in results] == ["controller"]
    assert session.calls == [("irrigation-config", None)]
    assert settings.controller_file.exists()
    assert not settings.schedule_file.exists()
    assert not settings.access_users_file.exists()


@pytest.mark.parametrize("error_type", [requests.ConnectionError, requests.ConnectTimeout, requests.ReadTimeout])
def test_airtable_sync_retries_transient_failures(tmp_path, monkeypatch, error_type):
    settings = _settings(tmp_path)
    payload = {"records": [{"id": "recovered"}]}
    session = Mock()
    session.get.side_effect = [error_type("disconnected")] * 3 + [FakeResponse(payload)]
    sleep = Mock()
    monkeypatch.setattr("mqtt_schedule.airtable_sync.time.sleep", sleep)

    AirtableSyncService(settings, session=session).sync_targets({"controller"})

    assert session.get.call_count == 4
    assert [call.args[0] for call in sleep.call_args_list] == [1, 2, 4]
    assert json.loads(settings.controller_file.read_text()) == payload
    assert all(call.kwargs["timeout"] == 30 for call in session.get.call_args_list)


def test_airtable_sync_exhausted_retries_preserve_export_on_later_page(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    original = '{"records": [{"id": "existing"}]}\n'
    settings.controller_file.write_text(original)
    session = Mock()
    session.get.side_effect = [
        FakeResponse({"records": [{"id": "first"}], "offset": "next-page"}),
        *[requests.ConnectionError("disconnected") for _ in range(4)],
    ]
    sleep = Mock()
    monkeypatch.setattr("mqtt_schedule.airtable_sync.time.sleep", sleep)

    with pytest.raises(requests.ConnectionError):
        AirtableSyncService(settings, session=session).sync_targets({"controller"})

    assert session.get.call_count == 5
    assert settings.controller_file.read_text() == original
    assert not settings.controller_file.with_suffix(".json.tmp").exists()
    assert [call.kwargs["params"] for call in session.get.call_args_list] == [
        {}, {"offset": "next-page"}, {"offset": "next-page"},
        {"offset": "next-page"}, {"offset": "next-page"},
    ]


def test_airtable_sync_retry_recovers_later_page_without_duplicate_records(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    session = Mock()
    session.get.side_effect = [
        FakeResponse({"records": [{"id": "first"}], "offset": "next-page"}),
        requests.ConnectionError("disconnected"),
        FakeResponse({"records": [{"id": "second"}]}),
    ]
    monkeypatch.setattr("mqtt_schedule.airtable_sync.time.sleep", Mock())

    AirtableSyncService(settings, session=session).sync_targets({"controller"})

    assert json.loads(settings.controller_file.read_text()) == {
        "records": [{"id": "first"}, {"id": "second"}],
    }


@pytest.mark.parametrize("failure", [requests.HTTPError("unauthorized"), ValueError("invalid JSON")])
def test_airtable_sync_does_not_retry_response_errors(tmp_path, monkeypatch, failure):
    settings = _settings(tmp_path)
    response = Mock()
    if isinstance(failure, requests.HTTPError):
        response.raise_for_status.side_effect = failure
    else:
        response.json.side_effect = failure
    session = Mock()
    session.get.return_value = response
    sleep = Mock()
    monkeypatch.setattr("mqtt_schedule.airtable_sync.time.sleep", sleep)

    with pytest.raises(type(failure)):
        AirtableSyncService(settings, session=session).sync_targets({"controller"})

    session.get.assert_called_once()
    sleep.assert_not_called()
    assert not settings.controller_file.exists()
