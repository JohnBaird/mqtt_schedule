import json
from pathlib import Path

from mqtt_schedule.controller_status import ControllerStatusStore
from mqtt_schedule.csv_reporting import LegacyCsvRecorder
from mqtt_schedule.inbound import AccessRequestMessageHandler
from mqtt_schedule.mqtt_adapter import (
    MQTTBrokerSettings,
    MQTTCommandEncoder,
    MQTTInboundMessage,
    MQTTMaintenancePublisher,
    RecordingMQTTClient,
)
from mqtt_schedule.settings import RuntimeSettings


def test_access_request_handler_publishes_legacy_response_for_grant(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "rec-1",
                        "fields": {
                            "firstName": "John",
                            "lastName": "Baird",
                            "enabled": "true",
                            "pinNumber": "12345",
                            "accessGroups": ["group1"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        transaction_csv_file=tmp_path / "transactions.csv",
        temperature_csv_file=tmp_path / "temperature.csv",
        csv_backup_dir=tmp_path / "csv_backup",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
                session_client_id="6410332930780559595",
                host_name="server",
                ip_address="192.168.1.53",
                program_version="MQTT_Schedule v1.0.7",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
        csv_recorder=LegacyCsvRecorder.from_settings(settings),
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_access_request/242606363309393/281261212083555",
            payload=json.dumps(
                {
                    "_iD": "req-access-1",
                    "dateTime": "2026-06-22  15:45:58",
                    "pinNumber": "12345",
                }
            ),
        )
    )

    assert handler.subscription_topics() == [
        "SPV1.0/irrigation/stc_access_request/+/281261212083555",
        "SPV1.0/irrigation/stc_online_status_request/+/281261212083555",
        "SPV1.0/irrigation/stc_input_status_request/+/281261212083555",
        "SPV1.0/irrigation/stc_online_status_response/+/281261212083555",
        "SPV1.0/irrigation/stc_input_status_response/+/281261212083555",
        "SPV1.0/irrigation/stc_temperature_response/+/281261212083555",
        "SPV1.0/irrigation/stc_config_file_response/+/281261212083555",
        "SPV1.0/irrigation/stc_transaction_response/+/281261212083555",
    ]
    assert client.published[0][0] == (
        "SPV1.0/irrigation/stc_access_response/281261212083555/242606363309393"
    )
    payload = json.loads(client.published[0][1])
    assert payload["granted"] is True
    assert payload["fullName"] == "John Baird"
    assert payload["pinNumber"] == "12345"
    assert "decision_reason=granted" in caplog.text
    assert settings.transaction_csv_file.exists()
    csv_lines = settings.transaction_csv_file.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == "_iD,latency,dateTime,transactionType,idNumber,UniqueId,fullName,serialSource"
    assert csv_lines[1] == "req-access-1,,2026-06-22  15:45:58,irrigation,12345,group1,John Baird,242606363309393"


def test_access_request_handler_publishes_reject_for_unknown_credential(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_access_request/242606363309393/281261212083555",
            payload=json.dumps({"pinNumber": "99999"}),
        )
    )

    payload = json.loads(client.published[0][1])
    assert payload["granted"] is False
    assert payload["fullName"] == "Unknown"
    assert payload["pinNumber"] == "99999"
    assert "decision_reason=credential_not_found" in caplog.text


def test_access_request_handler_rejects_when_access_users_file_is_missing(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_access_request/242606363309393/281261212083555",
            payload=json.dumps({"pinNumber": "12345"}),
        )
    )

    payload = json.loads(client.published[0][1])
    assert payload["granted"] is False
    assert payload["fullName"] == "Unknown"
    assert payload["pinNumber"] == "12345"
    assert "decision_reason=access_user_data_unavailable" in caplog.text


def test_online_status_request_handler_publishes_legacy_response(tmp_path: Path) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
                session_client_id="6410332930780559595",
                host_name="server",
                ip_address="192.168.1.53",
                program_version="MQTT_Schedule v1.0.7",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
    )

    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_online_status_request/242606363309393/281261212083555",
            payload=json.dumps(
                {
                    "_iD": "req-1",
                    "clientId": "24590218897498728475",
                    "programVersion": "MQTT_GPIO v2.0.8",
                }
            ),
        )
    )

    assert client.published[0][0] == (
        "SPV1.0/irrigation/stc_online_status_response/281261212083555/242606363309393"
    )
    payload = json.loads(client.published[0][1])
    assert payload["response"] == "online"
    assert payload["reason"] == "requested"


def test_input_status_request_handler_publishes_legacy_response(tmp_path: Path) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
                session_client_id="6410332930780559595",
                host_name="server",
                ip_address="192.168.1.53",
                program_version="MQTT_Schedule v1.0.7",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
    )

    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_input_status_request/242606363309393/281261212083555",
            payload=json.dumps({"_iD": "req-2"}),
        )
    )

    assert client.published[0][0] == (
        "SPV1.0/irrigation/stc_input_status_response/281261212083555/242606363309393"
    )
    payload = json.loads(client.published[0][1])
    assert payload["inputs_category"] == "Input ports unavailable"
    assert payload["input_ports"] == 0


def test_access_request_handler_rejects_when_access_users_file_is_invalid_json(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text("{invalid", encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_access_request/242606363309393/281261212083555",
            payload=json.dumps({"pinNumber": "12345"}),
        )
    )

    payload = json.loads(client.published[0][1])
    assert payload["granted"] is False
    assert payload["fullName"] == "Unknown"
    assert payload["pinNumber"] == "12345"
    assert "decision_reason=access_user_data_unavailable" in caplog.text


def test_access_request_handler_logs_group_mismatch_reason(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "id": "rec-1",
                        "fields": {
                            "firstName": "John",
                            "lastName": "Baird",
                            "enabled": "true",
                            "pinNumber": "12345",
                            "accessGroups": ["group1"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group9",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_access_request/242606363309393/281261212083555",
            payload=json.dumps({"pinNumber": "12345"}),
        )
    )

    payload = json.loads(client.published[0][1])
    assert payload["granted"] is False
    assert payload["fullName"] == "John Baird"
    assert "decision_reason=group_mismatch" in caplog.text
    assert "configured_groups=group9" in caplog.text


def test_online_status_response_handler_consumes_legacy_payload(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
        controller_status_store=ControllerStatusStore(tmp_path / "controller_status.json"),
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_online_status_response/242606363309393/281261212083555",
            payload=json.dumps({"response": "online", "reason": "requested"}),
        )
    )

    assert client.published == []
    assert "online_status_response_handled" in caplog.text
    assert "response=online" in caplog.text
    assert "reason=requested" in caplog.text
    status_payload = json.loads((tmp_path / "controller_status.json").read_text(encoding="utf-8"))
    assert status_payload["controllers"]["242606363309393"]["last_response"] == "online"
    assert status_payload["controllers"]["242606363309393"]["last_reason"] == "requested"
    assert status_payload["controllers"]["242606363309393"]["online"] is True


def test_online_status_response_handler_requests_config_after_restart(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
        controller_status_store=ControllerStatusStore(tmp_path / "controller_status.json"),
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_online_status_response/242606363309393/281261212083555",
            payload=json.dumps({"response": "online", "reason": "restarted"}),
        )
    )

    assert len(client.published) == 1
    assert client.published[0][0] == (
        "SPV1.0/irrigation/stc_config_file_request/281261212083555/242606363309393"
    )
    assert "config_file_request_triggered" in caplog.text
    assert "online_status_response_handled" in caplog.text
    payload = json.loads(client.published[0][1])
    assert payload["hostName"] == ""
    assert payload["ipAddress"] == ""
    status_payload = json.loads((tmp_path / "controller_status.json").read_text(encoding="utf-8"))
    controller_status = status_payload["controllers"]["242606363309393"]
    assert controller_status["last_response"] == "online"
    assert controller_status["last_reason"] == "restarted"
    assert controller_status["online"] is True
    assert "last_restart_at" in controller_status
    assert "last_config_sync_request_at" in controller_status


def test_input_status_response_handler_consumes_legacy_payload(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_input_status_response/242606363309393/281261212083555",
            payload=json.dumps({"inputs_category": "mcp_io", "input_ports": 32896}),
        )
    )

    assert client.published == []
    assert "input_status_response_handled" in caplog.text
    assert "inputs_category=mcp_io" in caplog.text
    assert "input_ports=32896" in caplog.text


def test_temperature_response_handler_consumes_legacy_payload(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        transaction_csv_file=tmp_path / "transactions.csv",
        temperature_csv_file=tmp_path / "temperature.csv",
        csv_backup_dir=tmp_path / "csv_backup",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
        csv_recorder=LegacyCsvRecorder.from_settings(settings),
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_temperature_response/242606363309393/281261212083555",
            payload=json.dumps(
                {
                    "_iD": "req-1",
                    "dateTime": "2026-06-22  09:55:37",
                    "hostName": "raspberrypi",
                    "ipAddress": "192.168.1.170",
                    "sensorName": "CPU_temp",
                    "sensorValue": 48.2,
                    "temperatureUnits": "degC",
                }
            ),
        )
    )

    assert client.published == []
    assert "temperature_response_handled" in caplog.text
    assert "sensor_name=CPU_temp" in caplog.text
    assert "sensor_value=48.2" in caplog.text
    assert "temperature_units=degC" in caplog.text
    csv_lines = settings.temperature_csv_file.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == "_iD,dateTime,serialSource,ipAddress,hostName,sensorName,tempValue"
    assert csv_lines[1] == "req-1,2026-06-22  09:55:37,242606363309393,192.168.1.170,raspberrypi,CPU_temp,48.2"


def test_config_file_response_handler_writes_sysinfo_snapshot(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    clients_sysinfo_dir = tmp_path / "clients_sysinfo"
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=clients_sysinfo_dir,
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_config_file_response/242606363309393/281261212083555",
            payload=json.dumps({"sysConfig": {"temperature_units": "degC", "outputs": [1, 2, 3]}}),
        )
    )

    output_path = clients_sysinfo_dir / "sysinfo_242606363309393.json"
    assert output_path.exists()
    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["temperature_units"] == "degC"
    assert saved["outputs"] == [1, 2, 3]
    assert client.published == []
    assert "config_file_response_handled" in caplog.text


def test_transaction_response_handler_consumes_legacy_payload(tmp_path: Path, caplog) -> None:
    access_users_file = tmp_path / "airtable_access_users.json"
    access_users_file.write_text(json.dumps({"records": []}), encoding="utf-8")
    settings = RuntimeSettings(
        schedule_file=tmp_path / "airtable_schedule_data.json",
        controller_file=tmp_path / "airtable_config_data.json",
        access_users_file=access_users_file,
        clients_sysinfo_dir=tmp_path / "clients_sysinfo",
        transaction_csv_file=tmp_path / "transactions.csv",
        temperature_csv_file=tmp_path / "temperature.csv",
        csv_backup_dir=tmp_path / "csv_backup",
        openweather_current_file=tmp_path / "ow_records_current.json",
        openweather_forecast_file=tmp_path / "ow_records_forecast.json",
        tempest_data_dir=tmp_path / "tempest_weather_data",
        device_serial_file=tmp_path / "device_serial.txt",
        access_groups=("group1",),
    )
    client = RecordingMQTTClient()
    publisher = MQTTMaintenancePublisher(
        encoder=MQTTCommandEncoder(
            MQTTBrokerSettings(
                host="localhost",
                port=1883,
                source_serial="281261212083555",
            )
        ),
        client=client,
    )
    handler = AccessRequestMessageHandler(
        settings=settings,
        maintenance_publisher=publisher,
        source_serial="281261212083555",
        csv_recorder=LegacyCsvRecorder.from_settings(settings),
    )

    caplog.set_level("INFO")
    handler.handle_message(
        MQTTInboundMessage(
            topic="SPV1.0/irrigation/stc_transaction_response/242606363309393/281261212083555",
            payload=json.dumps(
                {
                    "_iD": "txn-1",
                    "timestamp": 1782136537000,
                    "dateTime": "2026-06-22  09:55:37",
                    "idNumber": "12345",
                    "UniqueId": "group-a",
                    "fullName": "John Baird",
                }
            ),
        )
    )

    assert client.published == []
    assert "transaction_response_handled" in caplog.text
    assert "transaction_id=txn-1" in caplog.text
    assert "id_number=12345" in caplog.text
    assert "unique_id=group-a" in caplog.text
    assert "full_name=John Baird" in caplog.text
    csv_lines = settings.transaction_csv_file.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0] == "_iD,latency,dateTime,transactionType,idNumber,UniqueId,fullName,serialSource"
    assert csv_lines[1].startswith("txn-1,")
    assert ",2026-06-22  09:55:37,irrigation,12345,group-a,John Baird,242606363309393" in csv_lines[1]
