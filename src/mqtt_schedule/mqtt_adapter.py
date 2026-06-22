from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from json import dumps
from typing import Callable, Protocol
from uuid import uuid4

from .app import CommandPublisher
from .domain import AccessDecision, AccessRequest, DueCommand

try:
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover
    mqtt = None


class MQTTClientProtocol(Protocol):
    def publish(self, topic: str, payload: str) -> object:
        ...

    def subscribe(self, topic: str) -> object:
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
class SPTopic:
    topic_version: str
    domain: str
    command: str
    source_serial: str
    destination_serial: str

    def as_topic_string(self) -> str:
        return "/".join(
            [
                self.topic_version,
                self.domain,
                self.command,
                self.source_serial,
                self.destination_serial,
            ]
        )

    @classmethod
    def parse(cls, topic: str) -> SPTopic | None:
        parts = (topic or "").strip("/").split("/")
        if len(parts) != 5:
            return None
        topic_version, domain, command, source_serial, destination_serial = parts
        if not all(parts):
            return None
        return cls(
            topic_version=topic_version,
            domain=domain,
            command=command,
            source_serial=source_serial,
            destination_serial=destination_serial,
        )


@dataclass(frozen=True)
class MQTTCommandMessage:
    topic: str
    payload: dict[str, object]

    def payload_json(self) -> str:
        return dumps(self.payload)


@dataclass(frozen=True)
class MQTTInboundMessage:
    topic: str
    payload: str


@dataclass(frozen=True)
class AccessResponseRequestContext:
    source_serial: str
    pin_code: str | None
    pin_number: str | None
    card_number: str | None
    face_id: str | None
    request_id: str | None


class MQTTCommandEncoder:
    def __init__(self, settings: MQTTBrokerSettings) -> None:
        self.settings = settings

    def encode(self, command: DueCommand) -> list[MQTTCommandMessage]:
        # IMPORTANT:
        # This payload shape is a wire protocol contract with deployed hardware.
        # Field names and timestamp formatting must remain legacy-compatible.
        messages: list[MQTTCommandMessage] = []
        for destination in command.controller_links:
            payload = self._base_payload(command.evaluated_at)
            payload.update(
                {
                    "onOff": command.on,
                    "timerValue": command.timer_ms,
                    "outputIndex": command.output_index,
                    "airtableOutputType": command.output_type,
                    "airtableZoneCategory": command.zone_category,
                    "airtableGroups": command.group_select,
                }
            )
            messages.append(
                self._message_for_destination(
                    command_name="stc_airtable_output_onoff_request",
                    destination=destination,
                    payload=payload,
                )
            )
        return messages

    def encode_online_status_request(self, destination_links: list[str], *, now: datetime | None = None) -> list[MQTTCommandMessage]:
        return self._encode_simple_command("stc_online_status_request", destination_links, now=now)

    def encode_input_status_request(self, destination_links: list[str], *, now: datetime | None = None) -> list[MQTTCommandMessage]:
        return self._encode_simple_command("stc_input_status_request", destination_links, now=now)

    def encode_temperature_request(self, destination_links: list[str], *, now: datetime | None = None) -> list[MQTTCommandMessage]:
        return self._encode_simple_command("stc_temperature_request", destination_links, now=now)

    def encode_sysinfo_request(self, destination_links: list[str], *, now: datetime | None = None) -> list[MQTTCommandMessage]:
        return self._encode_simple_command("stc_sysinfo_request", destination_links, now=now)

    def encode_config_file_request(self, destination_links: list[str], *, now: datetime | None = None) -> list[MQTTCommandMessage]:
        return self._encode_simple_command("stc_config_file_request", destination_links, now=now)

    def encode_online_status_response(
        self,
        destination: str,
        *,
        response: str = "online",
        reason: str = "requested",
        now: datetime | None = None,
    ) -> MQTTCommandMessage:
        payload = self._base_payload(now or datetime.now())
        payload.update({"response": response, "reason": reason})
        return self._message_for_destination(
            command_name="stc_online_status_response",
            destination=destination,
            payload=payload,
        )

    def encode_input_status_response(
        self,
        destination: str,
        *,
        inputs_category: str = "Input ports unavailable",
        input_ports: int = 0,
        now: datetime | None = None,
    ) -> MQTTCommandMessage:
        payload = self._base_payload(now or datetime.now())
        payload.update(
            {
                "inputs_category": inputs_category,
                "input_ports": input_ports,
            }
        )
        return self._message_for_destination(
            command_name="stc_input_status_response",
            destination=destination,
            payload=payload,
        )

    def encode_access_response(
        self,
        destination: str,
        *,
        granted: bool | None,
        full_name: str | None,
        pin_code: str | None,
        pin_number: str | None,
        card_number: str | None,
        face_id: str | None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> MQTTCommandMessage:
        payload = self._base_payload(now or datetime.now())
        if request_id:
            payload["_iD"] = request_id
        payload.update(
            {
                "granted": granted,
                "fullName": full_name,
                "pinCode": pin_code,
                "pinNumber": pin_number,
                "cardNumber": card_number,
                "faceId": face_id,
            }
        )
        return self._message_for_destination(
            command_name="stc_access_response",
            destination=destination,
            payload=payload,
        )

    def encode_access_response_for_request(
        self,
        request: AccessResponseRequestContext,
        decision: AccessDecision,
        *,
        now: datetime | None = None,
    ) -> MQTTCommandMessage:
        return self.encode_access_response(
            request.source_serial,
            granted=decision.granted,
            full_name=decision.full_name,
            pin_code=request.pin_code,
            pin_number=request.pin_number,
            card_number=request.card_number,
            face_id=request.face_id,
            request_id=request.request_id,
            now=now,
        )

    def _encode_simple_command(
        self,
        command_name: str,
        destination_links: list[str],
        *,
        now: datetime | None = None,
    ) -> list[MQTTCommandMessage]:
        evaluated_at = now or datetime.now()
        return [
            self._message_for_destination(
                command_name=command_name,
                destination=destination,
                payload=self._base_payload(evaluated_at),
            )
            for destination in destination_links
        ]

    def _message_for_destination(
        self,
        *,
        command_name: str,
        destination: str,
        payload: dict[str, object],
    ) -> MQTTCommandMessage:
        topic = SPTopic(
            topic_version=self.settings.topic_version,
            domain=self.settings.domain,
            command=command_name,
            source_serial=self.settings.source_serial,
            destination_serial=destination,
        ).as_topic_string()
        return MQTTCommandMessage(topic=topic, payload=payload)

    def _base_payload(self, now: datetime) -> dict[str, object]:
        return {
            "_iD": uuid4().hex[:24],
            "clientId": self.settings.session_client_id,
            "programVersion": self.settings.program_version,
            "hostName": self.settings.host_name,
            "ipAddress": self.settings.ip_address,
            "dateTime": now.strftime("%Y/%m/%d  %H:%M:%S"),
            "unixTime": int(now.timestamp()),
        }


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


class MQTTMaintenancePublisher:
    def __init__(
        self,
        *,
        encoder: MQTTCommandEncoder,
        client: MQTTClientProtocol | None = None,
    ) -> None:
        self.encoder = encoder
        self.client = client

    def publish_online_status_request(self, destination_links: list[str], *, now: datetime | None = None) -> None:
        self._publish_messages(self.encoder.encode_online_status_request(destination_links, now=now))

    def publish_input_status_request(self, destination_links: list[str], *, now: datetime | None = None) -> None:
        self._publish_messages(self.encoder.encode_input_status_request(destination_links, now=now))

    def publish_temperature_request(self, destination_links: list[str], *, now: datetime | None = None) -> None:
        self._publish_messages(self.encoder.encode_temperature_request(destination_links, now=now))

    def publish_config_file_request(self, destination_links: list[str], *, now: datetime | None = None) -> None:
        self._publish_messages(self.encoder.encode_config_file_request(destination_links, now=now))

    def publish_online_status_response(
        self,
        destination: str,
        *,
        response: str = "online",
        reason: str = "requested",
        now: datetime | None = None,
    ) -> None:
        self._publish_messages(
            [
                self.encoder.encode_online_status_response(
                    destination,
                    response=response,
                    reason=reason,
                    now=now,
                )
            ]
        )

    def publish_input_status_response(
        self,
        destination: str,
        *,
        inputs_category: str = "Input ports unavailable",
        input_ports: int = 0,
        now: datetime | None = None,
    ) -> None:
        self._publish_messages(
            [
                self.encoder.encode_input_status_response(
                    destination,
                    inputs_category=inputs_category,
                    input_ports=input_ports,
                    now=now,
                )
            ]
        )

    def publish_access_response_for_request(
        self,
        request: AccessResponseRequestContext,
        decision: AccessDecision,
        *,
        now: datetime | None = None,
    ) -> None:
        self._publish_messages(
            [self.encoder.encode_access_response_for_request(request, decision, now=now)]
        )

    def _publish_messages(self, messages: list[MQTTCommandMessage]) -> None:
        for message in messages:
            if self.client is None:
                print(message.topic)
                print(message.payload_json())
            else:
                self.client.publish(message.topic, message.payload_json())


class RecordingMQTTClient(MQTTClientProtocol):
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.subscribed: list[str] = []

    def publish(self, topic: str, payload: str) -> object:
        self.published.append((topic, payload))
        return {"topic": topic}

    def subscribe(self, topic: str) -> object:
        self.subscribed.append(topic)
        return {"topic": topic}


class PahoClientFactory:
    @staticmethod
    def connect(
        settings: MQTTBrokerSettings,
        *,
        subscriptions: list[str] | None = None,
        on_message: Callable[[MQTTInboundMessage], None] | None = None,
    ):
        if mqtt is None:  # pragma: no cover
            raise RuntimeError("paho-mqtt is not installed")

        logger = logging.getLogger("mqtt_schedule.mqtt_adapter")
        client = mqtt.Client()
        if settings.username:
            client.username_pw_set(settings.username, settings.password)

        subscribed_topics = list(subscriptions or [])

        if subscribed_topics:
            def _on_connect(client, userdata, flags, rc, properties=None):
                for topic in subscribed_topics:
                    client.subscribe(topic)
                    logger.info("mqtt_subscription_registered topic=%s", topic)

            client.on_connect = _on_connect

        if on_message is not None:
            def _on_message(client, userdata, message):
                try:
                    payload = message.payload.decode("utf-8") if isinstance(message.payload, bytes) else str(message.payload)
                    logger.info("mqtt_message_received topic=%s", message.topic)
                    on_message(MQTTInboundMessage(topic=message.topic, payload=payload))
                except Exception:
                    logger.exception("mqtt_message_handler_failed topic=%s", getattr(message, "topic", "<unknown>"))

            client.on_message = _on_message

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
