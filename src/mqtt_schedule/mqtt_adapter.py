from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from json import dumps
from typing import Protocol
from uuid import uuid4

from .app import CommandPublisher
from .domain import DueCommand

try:
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover
    mqtt = None


class MQTTClientProtocol(Protocol):
    def publish(self, topic: str, payload: str) -> object:
        ...


@dataclass(frozen=True)
class MQTTBrokerSettings:
    host: str
    port: int
    keepalive: int = 60
    username: str | None = None
    password: str | None = None
    topic_version: str = "SPV1.0"
    domain: str = "irrigation"
    source_serial: str = "server"
    session_client_id: str = "0000000000000000"
    host_name: str = ""
    ip_address: str = ""
    program_name: str = "mqtt_schedule"
    program_version: str = "MQTT_Schedule v1.0.7"


@dataclass(frozen=True)
class MQTTCommandMessage:
    topic: str
    payload: dict[str, object]

    def payload_json(self) -> str:
        return dumps(self.payload)


class MQTTCommandEncoder:
    def __init__(self, settings: MQTTBrokerSettings) -> None:
        self.settings = settings

    def encode(self, command: DueCommand) -> list[MQTTCommandMessage]:
        # IMPORTANT:
        # This payload shape is a wire protocol contract with deployed hardware.
        # Field names and timestamp formatting must remain legacy-compatible.
        messages: list[MQTTCommandMessage] = []
        for destination in command.controller_links:
            topic = "/".join(
                [
                    self.settings.topic_version,
                    self.settings.domain,
                    "stc_airtable_output_onoff_request",
                    self.settings.source_serial,
                    destination,
                ]
            )
            payload = {
                "_iD": uuid4().hex[:24],
                "clientId": self.settings.session_client_id,
                "programVersion": self.settings.program_version,
                "hostName": self.settings.host_name,
                "ipAddress": self.settings.ip_address,
                "dateTime": command.evaluated_at.strftime("%Y/%m/%d  %H:%M:%S"),
                "unixTime": int(command.evaluated_at.timestamp()),
                "onOff": command.on,
                "timerValue": command.timer_ms,
                "outputIndex": command.output_index,
                "airtableOutputType": command.output_type,
                "airtableZoneCategory": command.zone_category,
                "airtableGroups": command.group_select,
            }
            messages.append(MQTTCommandMessage(topic=topic, payload=payload))
        return messages


class PahoCommandPublisher(CommandPublisher):
    def __init__(self, client: MQTTClientProtocol, encoder: MQTTCommandEncoder) -> None:
        self.client = client
        self.encoder = encoder

    def publish_due_command(self, command: DueCommand) -> None:
        for message in self.encoder.encode(command):
            self.client.publish(message.topic, message.payload_json())


class StdoutCommandPublisher(CommandPublisher):
    def __init__(self, encoder: MQTTCommandEncoder) -> None:
        self.encoder = encoder

    def publish_due_command(self, command: DueCommand) -> None:
        for message in self.encoder.encode(command):
            print(message.topic)
            print(message.payload_json())


class RecordingMQTTClient(MQTTClientProtocol):
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, topic: str, payload: str) -> object:
        self.published.append((topic, payload))
        return {"topic": topic}


class PahoClientFactory:
    @staticmethod
    def connect(settings: MQTTBrokerSettings):
        if mqtt is None:  # pragma: no cover
            raise RuntimeError("paho-mqtt is not installed")

        client = mqtt.Client()
        if settings.username:
            client.username_pw_set(settings.username, settings.password)
        client.connect(settings.host, settings.port, settings.keepalive)
        client.loop_start()
        return client

    @staticmethod
    def close(client: object) -> None:
        disconnect = getattr(client, "disconnect", None)
        if callable(disconnect):
            disconnect()
        loop_stop = getattr(client, "loop_stop", None)
        if callable(loop_stop):
            loop_stop()


def linux_server_now() -> datetime:
    return datetime.now()
