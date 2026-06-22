from __future__ import annotations

import json
import logging
from datetime import datetime
from time import time

from .access_control import AccessDecisionService, FileAccessUserRepository
from .csv_reporting import LegacyCsvRecorder
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
        csv_recorder: LegacyCsvRecorder | None = None,
    ) -> None:
        self.settings = settings
        self.maintenance_publisher = maintenance_publisher
        self.source_serial = source_serial
        self.csv_recorder = csv_recorder
        self.logger = logging.getLogger("mqtt_schedule.inbound")

    def subscription_topics(self) -> list[str]:
        return [
            self._subscription_topic_for("stc_access_request"),
            self._subscription_topic_for("stc_online_status_request"),
            self._subscription_topic_for("stc_input_status_request"),
            self._subscription_topic_for("stc_online_status_response"),
            self._subscription_topic_for("stc_input_status_response"),
            self._subscription_topic_for("stc_temperature_response"),
            self._subscription_topic_for("stc_config_file_response"),
            self._subscription_topic_for("stc_transaction_response"),
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
        if parsed_topic.command == "stc_online_status_response":
            self._handle_online_status_response(message, parsed_topic)
            return
        if parsed_topic.command == "stc_input_status_response":
            self._handle_input_status_response(message, parsed_topic)
            return
        if parsed_topic.command == "stc_temperature_response":
            self._handle_temperature_response(message, parsed_topic)
            return
        if parsed_topic.command == "stc_config_file_response":
            self._handle_config_file_response(message, parsed_topic)
            return
        if parsed_topic.command == "stc_transaction_response":
            self._handle_transaction_response(message, parsed_topic)
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

    def _handle_online_status_response(self, message: MQTTInboundMessage, parsed_topic: SPTopic) -> None:
        self.logger.info("online_status_response_message_received topic=%s", message.topic)
        if parsed_topic.destination_serial != self.source_serial:
            self.logger.debug(
                "inbound_message_ignored reason=wrong_destination expected=%s actual=%s",
                self.source_serial,
                parsed_topic.destination_serial,
            )
            return

        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError as exc:
            self.logger.warning(
                "online_status_response_ignored reason=invalid_payload_json topic=%s detail=%s",
                message.topic,
                exc,
            )
            return

        response = _payload_str_or_none(payload.get("response"))
        reason = _payload_str_or_none(payload.get("reason"))
        if reason == "restarted":
            self.maintenance_publisher.publish_config_file_request([parsed_topic.source_serial])
            self.logger.info(
                "config_file_request_triggered source_serial=%s destination_serial=%s reason=%s",
                parsed_topic.source_serial,
                parsed_topic.destination_serial,
                reason,
            )
        self.logger.info(
            "online_status_response_handled source_serial=%s destination_serial=%s response=%s reason=%s",
            parsed_topic.source_serial,
            parsed_topic.destination_serial,
            response,
            reason,
        )

    def _handle_input_status_response(self, message: MQTTInboundMessage, parsed_topic: SPTopic) -> None:
        self.logger.info("input_status_response_message_received topic=%s", message.topic)
        if parsed_topic.destination_serial != self.source_serial:
            self.logger.debug(
                "inbound_message_ignored reason=wrong_destination expected=%s actual=%s",
                self.source_serial,
                parsed_topic.destination_serial,
            )
            return

        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError as exc:
            self.logger.warning(
                "input_status_response_ignored reason=invalid_payload_json topic=%s detail=%s",
                message.topic,
                exc,
            )
            return

        inputs_category = _payload_str_or_none(payload.get("inputs_category"))
        input_ports = payload.get("input_ports")
        self.logger.info(
            "input_status_response_handled source_serial=%s destination_serial=%s inputs_category=%s input_ports=%s",
            parsed_topic.source_serial,
            parsed_topic.destination_serial,
            inputs_category,
            input_ports,
        )

    def _handle_temperature_response(self, message: MQTTInboundMessage, parsed_topic: SPTopic) -> None:
        self.logger.info("temperature_response_message_received topic=%s", message.topic)
        if parsed_topic.destination_serial != self.source_serial:
            self.logger.debug(
                "inbound_message_ignored reason=wrong_destination expected=%s actual=%s",
                self.source_serial,
                parsed_topic.destination_serial,
            )
            return

        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError as exc:
            self.logger.warning(
                "temperature_response_ignored reason=invalid_payload_json topic=%s detail=%s",
                message.topic,
                exc,
            )
            return

        sensor_name = _payload_str_or_none(payload.get("sensorName")) or _payload_str_or_none(
            payload.get("sensor_name")
        )
        sensor_value = payload.get("sensorValue", payload.get("sensor_value"))
        temperature_units = _payload_str_or_none(payload.get("temperatureUnits")) or _payload_str_or_none(
            payload.get("temperature_units")
        )
        message_id = _payload_str_or_none(payload.get("_iD")) or ""
        date_time = _payload_str_or_none(payload.get("dateTime")) or ""
        ip_address = _payload_str_or_none(payload.get("ipAddress")) or ""
        host_name = _payload_str_or_none(payload.get("hostName")) or ""
        if self.csv_recorder is not None:
            self.csv_recorder.record_temperature_response(
                message_id=message_id,
                date_time=date_time,
                source_serial=parsed_topic.source_serial,
                ip_address=ip_address,
                host_name=host_name,
                sensor_name=sensor_name or "",
                temp_value="" if sensor_value is None else str(sensor_value),
            )

        self.logger.info(
            "temperature_response_handled source_serial=%s destination_serial=%s sensor_name=%s sensor_value=%s temperature_units=%s",
            parsed_topic.source_serial,
            parsed_topic.destination_serial,
            sensor_name,
            sensor_value,
            temperature_units,
        )

    def _handle_config_file_response(self, message: MQTTInboundMessage, parsed_topic: SPTopic) -> None:
        self.logger.info("config_file_response_message_received topic=%s", message.topic)
        if parsed_topic.destination_serial != self.source_serial:
            self.logger.debug(
                "inbound_message_ignored reason=wrong_destination expected=%s actual=%s",
                self.source_serial,
                parsed_topic.destination_serial,
            )
            return

        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError as exc:
            self.logger.warning(
                "config_file_response_ignored reason=invalid_payload_json topic=%s detail=%s",
                message.topic,
                exc,
            )
            return

        config_data = payload.get("sysConfig")
        if config_data is None:
            self.logger.warning(
                "config_file_response_ignored reason=missing_sysconfig source_serial=%s destination_serial=%s",
                parsed_topic.source_serial,
                parsed_topic.destination_serial,
            )
            return

        output_dir = self.settings.clients_sysinfo_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"sysinfo_{parsed_topic.source_serial}.json"
        output_path.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
        self.logger.info(
            "config_file_response_handled source_serial=%s destination_serial=%s output_path=%s",
            parsed_topic.source_serial,
            parsed_topic.destination_serial,
            output_path,
        )

    def _handle_transaction_response(self, message: MQTTInboundMessage, parsed_topic: SPTopic) -> None:
        self.logger.info("transaction_response_message_received topic=%s", message.topic)
        if parsed_topic.destination_serial != self.source_serial:
            self.logger.debug(
                "inbound_message_ignored reason=wrong_destination expected=%s actual=%s",
                self.source_serial,
                parsed_topic.destination_serial,
            )
            return

        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError as exc:
            self.logger.warning(
                "transaction_response_ignored reason=invalid_payload_json topic=%s detail=%s",
                message.topic,
                exc,
            )
            return

        latency_seconds = _latency_seconds_from_timestamp(payload.get("timestamp"))
        id_number = _payload_str_or_none(payload.get("idNumber"))
        unique_id = _payload_str_or_none(payload.get("UniqueId"))
        full_name = _payload_str_or_none(payload.get("fullName"))
        transaction_id = _payload_str_or_none(payload.get("_iD"))
        date_time = _payload_str_or_none(payload.get("dateTime")) or _legacy_datetime_from_timestamp(
            payload.get("timestamp")
        )
        if self.csv_recorder is not None:
            self.csv_recorder.record_transaction_response(
                transaction_id=transaction_id or "",
                latency=latency_seconds,
                date_time=date_time,
                transaction_type=parsed_topic.domain,
                id_number=id_number or "",
                unique_id=unique_id or "",
                full_name=full_name or "",
                source_serial=parsed_topic.source_serial,
            )

        self.logger.info(
            "transaction_response_handled source_serial=%s destination_serial=%s transaction_id=%s transaction_type=%s id_number=%s unique_id=%s full_name=%s latency_seconds=%s",
            parsed_topic.source_serial,
            parsed_topic.destination_serial,
            transaction_id,
            parsed_topic.domain,
            id_number,
            unique_id,
            full_name,
            latency_seconds,
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
            "access_request_handled source_serial=%s destination_serial=%s granted=%s full_name=%s matched_group=%s matched_credential=%s decision_reason=%s configured_groups=%s",
            request.source_serial,
            request.destination_serial,
            decision.granted,
            decision.full_name,
            decision.matched_group,
            decision.matched_credential,
            decision.decision_reason,
            ",".join(self.settings.access_groups),
        )


def _payload_str_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _latency_seconds_from_timestamp(value: object) -> str:
    if isinstance(value, bool):
        return "not received"
    if isinstance(value, (int, float)):
        current_ms = int(time() * 1000)
        return f"{(current_ms - int(value)) / 1000:.3f}"
    return "not received"


def _legacy_datetime_from_timestamp(value: object) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value) / 1000).strftime("%Y-%m-%d  %H:%M:%S")
    return ""


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
        decision_reason="access_user_data_unavailable",
    )
