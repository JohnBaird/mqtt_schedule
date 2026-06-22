import json
from datetime import datetime

from mqtt_schedule.domain import DueCommand
from mqtt_schedule.mqtt_adapter import (
    MQTTBrokerSettings,
    MQTTCommandEncoder,
    MQTTMaintenancePublisher,
    PahoCommandPublisher,
    RecordingMQTTClient,
    SPTopic,
)


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


def test_sp_topic_uses_legacy_five_segment_shape() -> None:
    topic = SPTopic(
        topic_version="SPV1.0",
        domain="irrigation",
        command="stc_online_status_request",
        source_serial="281261212083555",
        destination_serial="242606363309393",
    )

    assert topic.as_topic_string() == (
        "SPV1.0/irrigation/stc_online_status_request/281261212083555/242606363309393"
    )


def test_encode_online_status_request_uses_legacy_topic_shape() -> None:
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host="localhost",
            port=1883,
            source_serial="281261212083555",
            session_client_id="6410332930780559595",
            host_name="john-HP-ProDesk-600-G1-DM",
            ip_address="192.168.1.53",
            program_version="MQTT_Schedule v1.0.7",
        )
    )

    message = encoder.encode_online_status_request(
        ["242606363309393"],
        now=datetime(2026, 6, 20, 21, 5, 0),
    )[0]

    assert message.topic == (
        "SPV1.0/irrigation/stc_online_status_request/281261212083555/242606363309393"
    )
    assert message.payload["clientId"] == "6410332930780559595"
    assert message.payload["dateTime"] == "2026/06/20  21:05:00"
    assert message.payload["unixTime"] == 1782003900
    assert "onOff" not in message.payload


def test_encode_input_and_temperature_requests_use_legacy_topic_shape() -> None:
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host="localhost",
            port=1883,
            source_serial="281261212083555",
        )
    )

    input_request = encoder.encode_input_status_request(
        ["242606363309393"],
        now=datetime(2026, 6, 20, 21, 5, 0),
    )[0]
    temperature_request = encoder.encode_temperature_request(
        ["242606363309393"],
        now=datetime(2026, 6, 20, 21, 5, 0),
    )[0]

    assert input_request.topic == (
        "SPV1.0/irrigation/stc_input_status_request/281261212083555/242606363309393"
    )
    assert temperature_request.topic == (
        "SPV1.0/irrigation/stc_temperature_request/281261212083555/242606363309393"
    )


def test_encode_sysinfo_and_config_requests_use_legacy_topic_shape() -> None:
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host="localhost",
            port=1883,
            source_serial="281261212083555",
        )
    )

    sysinfo_request = encoder.encode_sysinfo_request(
        ["242606363309393"],
        now=datetime(2026, 6, 20, 21, 5, 0),
    )[0]
    config_request = encoder.encode_config_file_request(
        ["242606363309393"],
        now=datetime(2026, 6, 20, 21, 5, 0),
    )[0]

    assert sysinfo_request.topic == (
        "SPV1.0/irrigation/stc_sysinfo_request/281261212083555/242606363309393"
    )
    assert config_request.topic == (
        "SPV1.0/irrigation/stc_config_file_request/281261212083555/242606363309393"
    )


def test_encode_online_status_and_access_responses_use_legacy_topic_shape() -> None:
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host="localhost",
            port=1883,
            source_serial="281261212083555",
        )
    )

    online_response = encoder.encode_online_status_response(
        "242606363309393",
        response="online",
        reason="requested",
        now=datetime(2026, 6, 20, 21, 5, 0),
    )
    access_response = encoder.encode_access_response(
        "242606363309393",
        granted=True,
        full_name="John Baird",
        pin_code="1234",
        pin_number="1",
        card_number="100",
        face_id="f-1",
        now=datetime(2026, 6, 20, 21, 5, 0),
    )

    assert online_response.topic == (
        "SPV1.0/irrigation/stc_online_status_response/281261212083555/242606363309393"
    )
    assert online_response.payload["response"] == "online"
    assert online_response.payload["reason"] == "requested"
    assert access_response.topic == (
        "SPV1.0/irrigation/stc_access_response/281261212083555/242606363309393"
    )
    assert access_response.payload["granted"] is True
    assert access_response.payload["fullName"] == "John Baird"


def test_encode_input_status_response_uses_legacy_topic_shape() -> None:
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host="localhost",
            port=1883,
            source_serial="281261212083555",
        )
    )

    input_response = encoder.encode_input_status_response(
        "242606363309393",
        inputs_category="Input ports unavailable",
        input_ports=0,
        now=datetime(2026, 6, 20, 21, 5, 0),
    )

    assert input_response.topic == (
        "SPV1.0/irrigation/stc_input_status_response/281261212083555/242606363309393"
    )
    assert input_response.payload["inputs_category"] == "Input ports unavailable"
    assert input_response.payload["input_ports"] == 0


def test_maintenance_publisher_publishes_config_file_request() -> None:
    client = RecordingMQTTClient()
    encoder = MQTTCommandEncoder(
        MQTTBrokerSettings(
            host="localhost",
            port=1883,
            source_serial="281261212083555",
        )
    )
    publisher = MQTTMaintenancePublisher(
        encoder=encoder,
        client=client,
    )

    publisher.publish_config_file_request(
        ["242606363309393"],
        now=datetime(2026, 6, 22, 10, 5, 0),
    )

    assert client.published[0][0] == (
        "SPV1.0/irrigation/stc_config_file_request/281261212083555/242606363309393"
    )
