import json
from datetime import datetime

from mqtt_schedule.domain import DueCommand
from mqtt_schedule.mqtt_adapter import MQTTBrokerSettings, MQTTCommandEncoder, PahoCommandPublisher, RecordingMQTTClient


def test_encodes_legacy_mqtt_command_shape() -> None:
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host="localhost",
            port=1883,
            source_serial="server-123",
            session_client_id="6410332930780559595",
            host_name="john-HP-ProDesk-600-G1-DM",
            ip_address="192.168.1.53",
            program_name="mqtt_schedule",
            program_version="MQTT_Schedule v1.0.7",
        )
    )

    command = DueCommand(
        schedule_record_id="rec-1",
        controller_links=["242606363309393"],
        output_type="output-irrigation",
        output_index=7,
        on=True,
        timer_ms=900_000,
        group_select=["group-a"],
        zone_category="Irrigation",
        evaluated_at=datetime(2026, 6, 20, 11, 45, 0),
    )

    message = encoder.encode(command)[0]

    assert message.topic == "SPV1.0/irrigation/stc_airtable_output_onoff_request/server-123/242606363309393"
    assert list(message.payload.keys()) == [
        "_iD",
        "clientId",
        "programVersion",
        "hostName",
        "ipAddress",
        "dateTime",
        "unixTime",
        "onOff",
        "timerValue",
        "outputIndex",
        "airtableOutputType",
        "airtableZoneCategory",
        "airtableGroups",
    ]
    assert message.payload["onOff"] is True
    assert message.payload["timerValue"] == 900_000
    assert message.payload["outputIndex"] == 7
    assert message.payload["clientId"] == "6410332930780559595"
    assert message.payload["programVersion"] == "MQTT_Schedule v1.0.7"
    assert message.payload["hostName"] == "john-HP-ProDesk-600-G1-DM"
    assert message.payload["ipAddress"] == "192.168.1.53"
    assert message.payload["dateTime"] == "2026/06/20  11:45:00"
    assert message.payload["unixTime"] == 1781970300
    assert message.payload["airtableOutputType"] == "output-irrigation"
    assert message.payload["airtableZoneCategory"] == "Irrigation"
    assert message.payload["airtableGroups"] == ["group-a"]
    assert isinstance(message.payload["_iD"], str)
    assert len(message.payload["_iD"]) == 24


def test_publisher_uses_client_for_each_destination() -> None:
    client = RecordingMQTTClient()
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host="localhost",
            port=1883,
            source_serial="server-123",
            session_client_id="6410332930780559595",
            host_name="host",
            ip_address="192.168.1.53",
        )
    )
    publisher = PahoCommandPublisher(client=client, encoder=encoder)

    command = DueCommand(
        schedule_record_id="rec-1",
        controller_links=["one", "two"],
        output_type="output-general",
        output_index=2,
        on=True,
        timer_ms=30_000,
        group_select=["group-a"],
        zone_category="General",
        evaluated_at=datetime(2026, 6, 20, 11, 45, 0),
    )

    publisher.publish_due_command(command)

    assert len(client.published) == 2
    first_topic, first_payload = client.published[0]
    assert first_topic.endswith("/one")
    decoded = json.loads(first_payload)
    assert decoded["airtableOutputType"] == "output-general"


def test_payload_json_preserves_legacy_field_names() -> None:
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host="localhost",
            port=1883,
            source_serial="server-123",
            session_client_id="6410332930780559595",
            host_name="john-HP-ProDesk-600-G1-DM",
            ip_address="192.168.1.53",
            program_name="mqtt_schedule",
            program_version="MQTT_Schedule v1.0.7",
        )
    )

    command = DueCommand(
        schedule_record_id="rec-1",
        controller_links=["242606363309393"],
        output_type="output-irrigation",
        output_index=7,
        on=True,
        timer_ms=900_000,
        group_select=["group-a"],
        zone_category="Irrigation",
        evaluated_at=datetime(2026, 6, 20, 11, 45, 0),
    )

    payload_json = encoder.encode(command)[0].payload_json()
    decoded = json.loads(payload_json)

    assert set(decoded.keys()) == {
        "_iD",
        "clientId",
        "programVersion",
        "hostName",
        "ipAddress",
        "dateTime",
        "unixTime",
        "onOff",
        "timerValue",
        "outputIndex",
        "airtableOutputType",
        "airtableZoneCategory",
        "airtableGroups",
    }
