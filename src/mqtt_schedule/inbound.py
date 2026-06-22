from __future__ import annotations

import json
import logging

from .access_control import AccessDecisionService, FileAccessUserRepository
from .domain import AccessDecision, AccessRequest
from .mqtt_adapter import MQTTInboundMessage, MQTTMaintenancePublisher, SPTopic
from .settings import RuntimeSettings


class AccessRequestMessageHandler:
    def __init__(
        self,
        *,
        settings: RuntimeSettings,
        maintenance_publisher: MQTTMaintenancePublisher,
        source_serial: str,
    ) -> None:
        self.settings = settings
        self.maintenance_publisher = maintenance_publisher
        self.source_serial = source_serial
        self.logger = logging.getLogger("mqtt_schedule.inbound")

    def subscription_topics(self) -> list[str]:
        return [
            self._subscription_topic_for("stc_access_request"),
            self._subscription_topic_for("stc_online_status_request"),
            self._subscription_topic_for("stc_input_status_request"),
        ]

    def handle_message(self, message: MQTTInboundMessage) -> None:
        parsed_topic = SPTopic.parse(message.topic)
        if parsed_topic is None:
            self.logger.warning("inbound_message_ignored reason=invalid_topic topic=%s", message.topic)
            return
        if parsed_topic.command == "stc_access_request":
            self._handle_access_request(message, parsed_topic)
            return
        if parsed_topic.command == "stc_online_status_request":
            self._handle_online_status_request(message, parsed_topic)
            return
        if parsed_topic.command == "stc_input_status_request":
            self._handle_input_status_request(message, parsed_topic)
            return
        self.logger.debug(
            "inbound_message_ignored reason=unsupported_command command=%s topic=%s",
            parsed_topic.command,
            message.topic,
        )

    def _subscription_topic_for(self, command: str) -> str:
        return "/".join(
            [
                self.settings.mqtt_topic_version,
                self.settings.mqtt_domain,
                command,
                "+",
                self.source_serial,
            ]
        )

    def _handle_online_status_request(self, message: MQTTInboundMessage, parsed_topic: SPTopic) -> None:
        self.logger.info("online_status_request_message_received topic=%s", message.topic)
        if parsed_topic.destination_serial != self.source_serial:
            self.logger.debug(
                "inbound_message_ignored reason=wrong_destination expected=%s actual=%s",
                self.source_serial,
                parsed_topic.destination_serial,
            )
            return

        self.maintenance_publisher.publish_online_status_response(
            parsed_topic.source_serial,
            response="online",
            reason="requested",
        )
        self.logger.info(
            "online_status_request_handled source_serial=%s destination_serial=%s response=online reason=requested",
            parsed_topic.source_serial,
            parsed_topic.destination_serial,
        )

    def _handle_input_status_request(self, message: MQTTInboundMessage, parsed_topic: SPTopic) -> None:
        self.logger.info("input_status_request_message_received topic=%s", message.topic)
        if parsed_topic.destination_serial != self.source_serial:
            self.logger.debug(
                "inbound_message_ignored reason=wrong_destination expected=%s actual=%s",
                self.source_serial,
                parsed_topic.destination_serial,
            )
            return

        self.maintenance_publisher.publish_input_status_response(
            parsed_topic.source_serial,
            inputs_category="Input ports unavailable",
            input_ports=0,
        )
        self.logger.info(
            "input_status_request_handled source_serial=%s destination_serial=%s inputs_category=%s input_ports=%s",
            parsed_topic.source_serial,
            parsed_topic.destination_serial,
            "Input ports unavailable",
            0,
        )

    def _handle_access_request(self, message: MQTTInboundMessage, parsed_topic: SPTopic) -> None:
        self.logger.info("access_request_message_received topic=%s", message.topic)
        if parsed_topic.destination_serial != self.source_serial:
            self.logger.debug(
                "inbound_message_ignored reason=wrong_destination expected=%s actual=%s",
                self.source_serial,
                parsed_topic.destination_serial,
            )
            return

        self._process_access_request(message, parsed_topic)

    def _process_access_request(self, message: MQTTInboundMessage, parsed_topic: SPTopic) -> None:
        if parsed_topic.command != "stc_access_request":
            self.logger.debug(
                "inbound_message_ignored reason=unsupported_command command=%s topic=%s",
                parsed_topic.command,
                message.topic,
            )
            return

        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError as exc:
            self.logger.warning(
                "access_request_ignored reason=invalid_payload_json topic=%s detail=%s",
                message.topic,
                exc,
            )
            return

        request = AccessRequest(
            source_serial=parsed_topic.source_serial,
            destination_serial=parsed_topic.destination_serial,
            pin_code=_payload_str_or_none(payload.get("pinCode")),
            pin_number=_payload_str_or_none(payload.get("pinNumber")),
            card_number=_payload_str_or_none(payload.get("cardNumber")),
            face_id=_payload_str_or_none(payload.get("faceId")),
        )
        self.logger.info(
            "access_request_parsed source_serial=%s destination_serial=%s pin_code_present=%s pin_number_present=%s card_number_present=%s face_id_present=%s",
            request.source_serial,
            request.destination_serial,
            bool(request.pin_code),
            bool(request.pin_number),
            bool(request.card_number),
            bool(request.face_id),
        )

        try:
            decision = AccessDecisionService(
                repository=FileAccessUserRepository(self.settings.access_users_file),
                access_groups=list(self.settings.access_groups),
            ).decide(request)
        except (FileNotFoundError, OSError, json.JSONDecodeError) as exc:
            self.logger.warning(
                "access_request_fallback_reject reason=access_user_data_unavailable path=%s detail=%s",
                self.settings.access_users_file,
                exc,
            )
            decision = _fallback_reject_decision(request)

        self.maintenance_publisher.publish_access_response_for_request(request, decision)
        self.logger.info(
            "access_request_handled source_serial=%s destination_serial=%s granted=%s full_name=%s matched_group=%s matched_credential=%s",
            request.source_serial,
            request.destination_serial,
            decision.granted,
            decision.full_name,
            decision.matched_group,
            decision.matched_credential,
        )


def _payload_str_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _fallback_reject_decision(request: AccessRequest):
    matched_credential = next(
        (
            value
            for value in (
                request.pin_code,
                request.pin_number,
                request.card_number,
                request.face_id,
            )
            if value
        ),
        None,
    )
    return AccessDecision(
        granted=False,
        full_name="Unknown",
        matched_group=None,
        matched_credential=matched_credential,
    )
