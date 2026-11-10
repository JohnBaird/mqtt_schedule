from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from mqtt_schedule.airtable_repositories import FileControllerRepository
from mqtt_schedule.cli import build_controller_repository
from mqtt_schedule.inbound import AccessRequestMessageHandler
from mqtt_schedule.input_alert_processing import InputAlertProcessor, InputAlertReportStore
from mqtt_schedule.mqtt_adapter import MQTTInboundMessage, PahoClientFactory, MQTTBrokerSettings
from mqtt_schedule.notifications import EmailNotifications, EmailSubmission, SmsNotifications, SmsSubmission
from mqtt_schedule.settings import RuntimeSettings


NOW = 1794256294
SERIAL = "44864172347607"
SERVER = "281261212083555"
TOPIC = f"SPV1.0/irrigation/stc_input_status_response/{SERIAL}/{SERVER}"


def rule(*, index=0, edge="negative", enabled=True, channels=None):
    return {"id": f"rec-{index}-{edge}", "fields": {
        "Name": f"Input {index} {edge}", "enabled": enabled, "controller": ["recController"],
        "inputCategory": "Digital GPIO", "inputIndex": index, "edge": edge,
        "channels": ["sms", "email"] if channels is None else channels, "message": "Test input changed",
    }}


def report(**changes):
    value = {"_iD": "report-1", "unixTime": NOW, "inputs_category": "Digital GPIO",
             "positive_edges": 0, "negative_edges": 1, "inputActiveBitmap": 1}
    value.update(changes)
    return value


class QueueSpy:
    def __init__(self, accepted=True):
        self.calls = []
        self.accepted = accepted

    def notify(self, **kwargs):
        self.calls.append(kwargs)
        return self.accepted


@pytest.fixture
def setup(tmp_path):
    settings = RuntimeSettings(
        schedule_file=tmp_path / "schedule.json", controller_file=tmp_path / "controllers.json",
        access_users_file=tmp_path / "users.json", clients_sysinfo_dir=tmp_path / "sysinfo",
        openweather_current_file=tmp_path / "current.json", openweather_forecast_file=tmp_path / "forecast.json",
        tempest_data_dir=tmp_path / "tempest", device_serial_file=tmp_path / "serial.txt",
        input_alerts_file=tmp_path / "rules.json", input_alert_state_file=tmp_path / "state" / "reports.json",
        input_alerts_enabled=True, sms_enabled=True, email_enabled=True,
    )
    settings.controller_file.write_text(json.dumps({"records": [{"id": "recController", "fields": {
        "Name": "Test RP2350", "nameLink": SERIAL, "enabled": True,
    }}]}), encoding="utf-8")
    settings.input_alerts_file.write_text(json.dumps({"records": [rule()]}), encoding="utf-8")
    return settings


def processor(settings, *, sms=None, email=None, **kwargs):
    return InputAlertProcessor(
        settings=settings, controller_repository=FileControllerRepository(settings.controller_file),
        sms_notifications=sms, email_notifications=email, clock=lambda: float(NOW), **kwargs,
    )


def save_rules(settings, *rules):
    settings.input_alerts_file.write_text(json.dumps({"records": list(rules)}), encoding="utf-8")


@pytest.mark.parametrize("reason", ["requested", "input_changed", None])
def test_requested_and_unsolicited_input_responses_dispatch_without_a_request(setup, reason):
    sms, email = QueueSpy(), QueueSpy()
    handler = AccessRequestMessageHandler(
        settings=setup, maintenance_publisher=None, source_serial=SERVER,
        input_alert_processor=processor(setup, sms=sms, email=email),
    )
    handler.handle_message(MQTTInboundMessage(TOPIC, json.dumps(report(reason=reason))))
    assert len(sms.calls) == len(email.calls) == 1
    assert sms.calls[0]["event"] == email.calls[0]["event"] == "input_edge"
    assert sms.calls[0]["body"] == email.calls[0]["body"]
    assert SERIAL in sms.calls[0]["body"] and "report-1" in sms.calls[0]["body"]
    assert "input: 0; edge: negative" in sms.calls[0]["body"]


def test_both_masks_decode_independently_and_match_category_and_direction(setup):
    save_rules(setup, *(rule(index=index, edge=edge) for index, edge in (
        (0, "negative"), (2, "negative"), (1, "positive"), (7, "positive"), (0, "positive"))))
    sms = QueueSpy()
    processor(setup, sms=sms).handle_response(source_serial=SERIAL, payload=report(positive_edges=131, negative_edges=5))
    assert len(sms.calls) == 5
    bodies = [call["body"] for call in sms.calls]
    assert sum("input: 0;" in body for body in bodies) == 2
    assert any("input: 7; edge: positive" in body for body in bodies)


def test_same_report_is_suppressed_across_restart_but_new_id_with_same_mask_is_new(setup, caplog):
    caplog.set_level(logging.INFO)
    sms = QueueSpy()
    processor(setup, sms=sms).handle_response(source_serial=SERIAL, payload=report())
    restarted = processor(setup, sms=sms)
    restarted.handle_response(source_serial=SERIAL, payload=report())
    restarted.handle_response(source_serial=SERIAL, payload=report(_iD="report-2"))
    assert len(sms.calls) == 2
    assert "reason=duplicate" in caplog.text


def test_missing_rule_warns_per_new_edge_with_trace_fields_not_duplicate(setup, caplog):
    save_rules(setup)
    sms = QueueSpy()
    handler = processor(setup, sms=sms)
    handler.handle_response(source_serial=SERIAL, payload=report(negative_edges=5))
    handler.handle_response(source_serial=SERIAL, payload=report(negative_edges=5))
    warnings = [record for record in caplog.records if "input_alert_rule_missing" in record.message]
    assert len(warnings) == 2
    assert all(record.levelno == logging.WARNING for record in warnings)
    assert "input_index=0 edge=negative report_id=report-1" in warnings[0].message
    assert "input_index=2 edge=negative" in warnings[1].message
    assert all(f"source_serial={SERIAL}" in record.message and "inputs_category=Digital GPIO" in record.message for record in warnings)
    assert sms.calls == []


@pytest.mark.parametrize("enabled,channels", [(False, ["sms"]), ("false", ["sms"]), (True, [])])
def test_disabled_rule_and_empty_channels_are_intentional_not_missing(setup, enabled, channels, caplog):
    save_rules(setup, rule(enabled=enabled, channels=channels))
    sms = QueueSpy()
    processor(setup, sms=sms).handle_response(source_serial=SERIAL, payload=report())
    assert sms.calls == []
    assert "input_alert_rule_missing" not in caplog.text


@pytest.mark.parametrize("changes", [{"negative_edges": 0}, {"positive_edges": 0, "negative_edges": 0},
                                    {"positive_edges": None}, {"negative_edges": True}, {"negative_edges": "1"},
                                    {"negative_edges": -1}, {"positive_edges": 256}, {"negative_edges": 1.0},
                                    {"_iD": None}, {"_iD": ""}, {"_iD": "bad\nlog"},
                                    {"inputs_category": None}, {"unixTime": None}, {"unixTime": True},
                                    {"unixTime": float("nan")}, {"unixTime": 10 ** 400},
                                    {"unixTime": NOW - 301}, {"unixTime": NOW + 61}])
def test_invalid_empty_or_stale_reports_do_not_send_or_claim(setup, changes, caplog):
    sms = QueueSpy()
    processor(setup, sms=sms).handle_response(source_serial=SERIAL, payload=report(**changes))
    assert sms.calls == []
    assert not setup.input_alert_state_file.exists()
    assert "input_alert_rule_missing" not in caplog.text


def test_legacy_response_without_edges_is_unchanged(setup, caplog):
    processor(setup).handle_response(source_serial=SERIAL, payload={"inputs_category": "mcp_io", "input_ports": 32896})
    assert not setup.input_alert_state_file.exists()
    assert caplog.records == []


@pytest.mark.parametrize("changes", [{"retained": True}, {"dry_run": True}, {"enabled": False}])
def test_retained_dry_run_and_feature_switch_block_all_processing(setup, changes):
    if "enabled" in changes:
        setup = replace(setup, input_alerts_enabled=changes["enabled"])
    sms = QueueSpy()
    handler = processor(setup, sms=sms, dry_run=changes.get("dry_run", False))
    handler.handle_response(source_serial=SERIAL, payload=report(), retained=changes.get("retained", False))
    assert sms.calls == []
    assert not setup.input_alert_state_file.exists()


@pytest.mark.parametrize("sms_enabled,email_enabled", [(True, False), (False, True), (False, False), (True, True)])
def test_channel_master_switches_are_independent(setup, sms_enabled, email_enabled):
    setup = replace(setup, sms_enabled=sms_enabled, email_enabled=email_enabled,
                    sms_service_start_enabled=False, email_service_start_enabled=False)
    sms, email = QueueSpy(), QueueSpy()
    processor(setup, sms=sms, email=email).handle_response(source_serial=SERIAL, payload=report())
    assert len(sms.calls) == int(sms_enabled)
    assert len(email.calls) == int(email_enabled)


@pytest.mark.parametrize("channels", [["sms"], ["email"]])
def test_rule_selects_channels(setup, channels):
    save_rules(setup, rule(channels=channels))
    sms, email = QueueSpy(), QueueSpy()
    processor(setup, sms=sms, email=email).handle_response(source_serial=SERIAL, payload=report())
    assert bool(sms.calls) == ("sms" in channels)
    assert bool(email.calls) == ("email" in channels)


def test_disabled_unknown_and_cli_excluded_controllers_never_alert(setup, caplog):
    sms = QueueSpy()
    handler = processor(setup, sms=sms)
    handler.handle_response(source_serial="999", payload=report())
    handler.controllers = build_controller_repository(settings=setup, cli_only_destinations=["999"])
    handler.handle_response(source_serial=SERIAL, payload=report())
    controllers = json.loads(setup.controller_file.read_text())
    controllers["records"][0]["fields"]["enabled"] = False
    setup.controller_file.write_text(json.dumps(controllers), encoding="utf-8")
    processor(setup, sms=sms).handle_response(source_serial=SERIAL, payload=report())
    assert sms.calls == [] and not setup.input_alert_state_file.exists()
    assert "input_alert_rule_missing" not in caplog.text


def test_category_mismatch_is_a_missing_rule_not_an_alert(setup, caplog):
    sms = QueueSpy()
    processor(setup, sms=sms).handle_response(source_serial=SERIAL, payload=report(inputs_category="Other GPIO"))
    assert sms.calls == []
    assert "input_alert_rule_missing" in caplog.text


def test_valid_rule_refresh_applies_without_restart(setup):
    sms = QueueSpy()
    handler = processor(setup, sms=sms)
    save_rules(setup, rule(enabled=False))
    handler.handle_response(source_serial=SERIAL, payload=report())
    save_rules(setup, rule())
    handler.handle_response(source_serial=SERIAL, payload=report(_iD="report-2"))
    assert len(sms.calls) == 1


@pytest.mark.parametrize("contents", ["not json", "[]", '{"records": []}',
                                     '{"version": 1, "reports": {"bad-key": 0}}'])
def test_corrupt_state_fails_closed_without_overwriting(setup, contents, caplog):
    setup.input_alert_state_file.parent.mkdir()
    setup.input_alert_state_file.write_text(contents, encoding="utf-8")
    sms = QueueSpy()
    processor(setup, sms=sms).handle_response(source_serial=SERIAL, payload=report())
    assert sms.calls == []
    assert setup.input_alert_state_file.read_text() == contents
    assert "reason=state_unavailable" in caplog.text


def test_unwritable_state_skips_send_and_duplicate_failure_does_not_hide_next_report(setup, monkeypatch, caplog):
    sms = QueueSpy()
    handler = processor(setup, sms=sms)
    original = handler.store.claim
    def fail(**kwargs):
        raise PermissionError("private filesystem detail")
    monkeypatch.setattr(handler.store, "claim", fail)
    handler.handle_response(source_serial=SERIAL, payload=report())
    assert not sms.calls and "reason=state_unavailable" in caplog.text
    assert "private filesystem detail" not in caplog.text
    monkeypatch.setattr(handler.store, "claim", original)
    handler.handle_response(source_serial=SERIAL, payload=report())
    assert len(sms.calls) == 1


def test_missing_or_invalid_rules_fail_closed_and_can_recover(setup, caplog):
    sms = QueueSpy()
    handler = processor(setup, sms=sms)
    setup.input_alerts_file.write_text("{}", encoding="utf-8")
    handler.handle_response(source_serial=SERIAL, payload=report())
    assert sms.calls == [] and not setup.input_alert_state_file.exists()
    assert "reason=configuration_unavailable" in caplog.text
    save_rules(setup, rule())
    handler.handle_response(source_serial=SERIAL, payload=report())
    assert len(sms.calls) == 1


def test_rejected_queue_is_logged_and_not_automatically_retried(setup, caplog):
    caplog.set_level(logging.INFO)
    sms, email = QueueSpy(accepted=False), QueueSpy()
    handler = processor(setup, sms=sms, email=email)
    handler.handle_response(source_serial=SERIAL, payload=report())
    handler.handle_response(source_serial=SERIAL, payload=report())
    assert len(sms.calls) == len(email.calls) == 1
    assert "channel=sms queued=False" in caplog.text and "channel=email queued=True" in caplog.text


def test_state_is_bounded_and_expires_old_reports(tmp_path):
    store = InputAlertReportStore(tmp_path / "reports.json")
    store.MAX_REPORTS = 3
    for index in range(4):
        assert store.claim(source_serial=SERIAL, category="Digital GPIO", report_id=str(index), now=NOW + index)
    assert len(json.loads(store.path.read_text())["reports"]) == 3
    assert not store.claim(source_serial=SERIAL, category="Digital GPIO", report_id="3", now=NOW + 10)
    assert store.claim(source_serial=SERIAL, category="Digital GPIO", report_id="3", now=NOW + 86404)
    assert len(json.loads(store.path.read_text())["reports"]) == 1


def test_metadata_for_same_id_is_scoped_by_controller_and_category(tmp_path):
    store = InputAlertReportStore(tmp_path / "reports.json")
    for serial, category in [(SERIAL, "one"), ("999", "one"), (SERIAL, "two")]:
        assert store.claim(source_serial=serial, category=category, report_id="same", now=NOW)


def test_concurrent_claims_for_same_report_only_succeed_once(tmp_path):
    store = InputAlertReportStore(tmp_path / "reports.json")
    def claim(_):
        return store.claim(source_serial=SERIAL, category="Digital GPIO", report_id="same", now=NOW)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(12)))
    assert sum(results) == 1


@pytest.mark.parametrize("contents", ["[]", "null", '{"records": [null]}'])
def test_malformed_controller_cache_is_logged_without_sending(setup, contents, caplog):
    setup.controller_file.write_text(contents, encoding="utf-8")
    sms = QueueSpy()
    processor(setup, sms=sms).handle_response(source_serial=SERIAL, payload=report())
    assert sms.calls == []
    assert "reason=configuration_unavailable" in caplog.text


def test_failed_atomic_state_replace_never_sends_and_can_recover(setup, monkeypatch, caplog):
    sms = QueueSpy()
    handler = processor(setup, sms=sms)
    original = Path.replace
    def fail(self, target):
        raise PermissionError("test failure")
    monkeypatch.setattr(Path, "replace", fail)
    handler.handle_response(source_serial=SERIAL, payload=report())
    assert sms.calls == []
    assert not setup.input_alert_state_file.exists()
    assert "reason=state_unavailable" in caplog.text
    monkeypatch.setattr(Path, "replace", original)
    handler.handle_response(source_serial=SERIAL, payload=report())
    assert len(sms.calls) == 1


def test_real_workers_submit_off_callback_thread_with_startup_switches_disabled(setup):
    calls, done = [], threading.Event()
    class Sender:
        def send(self, **kwargs):
            calls.append((kwargs, threading.get_ident()))
            if len(calls) == 2:
                done.set()
            return SmsSubmission("test-sms", "queued") if "to_number" in kwargs else EmailSubmission("test-email")
    sms = SmsNotifications(enabled=True, service_start_enabled=False, sender=Sender(), recipients=("+15550000001",))
    email = EmailNotifications(enabled=True, service_start_enabled=False, sender=Sender(), recipients=("test@example.test",))
    try:
        processor(setup, sms=sms, email=email).handle_response(source_serial=SERIAL, payload=report())
        assert done.wait(2)
        assert all(thread_id != threading.get_ident() for _, thread_id in calls)
    finally:
        sms.close()
        email.close()


def test_input_handler_rejects_wrong_destination_and_non_object_payload(setup):
    sms = QueueSpy()
    handler = AccessRequestMessageHandler(settings=setup, maintenance_publisher=None, source_serial=SERVER,
                                          input_alert_processor=processor(setup, sms=sms))
    handler.handle_message(MQTTInboundMessage(TOPIC.rsplit("/", 1)[0] + "/999", json.dumps(report())))
    handler.handle_message(MQTTInboundMessage(TOPIC, "[]"))
    handler.handle_message(MQTTInboundMessage(TOPIC, "not json"))
    handler.handle_message(MQTTInboundMessage(TOPIC, json.dumps(report()), retained=True))
    assert sms.calls == []


def test_paho_preserves_retained_metadata_without_changing_payload(monkeypatch):
    import mqtt_schedule.mqtt_adapter as adapter
    class Client:
        def connect(self, *args):
            pass
        def loop_start(self):
            pass
    client = Client()
    monkeypatch.setattr(adapter, "mqtt", SimpleNamespace(Client=lambda: client))
    messages = []
    PahoClientFactory.connect(MQTTBrokerSettings(host="localhost", port=1883), on_message=messages.append)
    raw = json.dumps(report())
    client.on_message(client, None, SimpleNamespace(topic=TOPIC, payload=raw.encode(), retain=True))
    assert messages == [MQTTInboundMessage(TOPIC, raw, retained=True)]
