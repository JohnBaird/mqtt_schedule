from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable

import requests

from .notifications import SmsSendError, SmsSubmission


def validate_phone_number(number: str) -> None:
    if re.fullmatch(r"\+[1-9][0-9]{1,14}", number) is None:
        raise ValueError("SMS numbers must use E.164 format")


@dataclass(frozen=True)
class TwilioSmsSettings:
    account_sid: str = field(repr=False)
    auth_token: str = field(repr=False)
    from_number: str = field(repr=False)


class TwilioSmsSender:
    def __init__(self, settings: TwilioSmsSettings, *, post: Callable | None = None) -> None:
        if re.fullmatch(r"AC[0-9a-fA-F]{32}", settings.account_sid) is None:
            raise ValueError("Twilio Account SID must start with AC and contain 32 hexadecimal characters")
        if not settings.auth_token.strip():
            raise ValueError("Twilio Auth Token is required")
        validate_phone_number(settings.from_number)
        self.settings = settings
        self._post = post or requests.post

    def send(self, *, to_number: str, body: str) -> SmsSubmission:
        validate_phone_number(to_number)
        try:
            response = self._post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.settings.account_sid}/Messages.json",
                auth=(self.settings.account_sid, self.settings.auth_token),
                data={"From": self.settings.from_number, "To": to_number, "Body": body},
                timeout=(5, 10),
                allow_redirects=False,
            )
        except requests.RequestException:
            # A lost response may follow a successful submission; do not retry automatically.
            raise SmsSendError("request_outcome_unknown") from None

        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if response.status_code != 201:
            provider_code = payload.get("code")
            raise SmsSendError(
                "twilio_http_error",
                http_status=response.status_code,
                provider_code=provider_code if type(provider_code) is int else None,
            )
        message_sid = payload.get("sid")
        status = payload.get("status")
        if (
            not isinstance(message_sid, str)
            or re.fullmatch(r"(?:SM|MM)[0-9a-fA-F]{32}", message_sid) is None
            or not isinstance(status, str)
            or status not in {"accepted", "queued", "sending", "sent", "delivered", "failed", "undelivered", "scheduled", "canceled"}
        ):
            raise SmsSendError("invalid_submission_response")
        return SmsSubmission(message_sid=message_sid, status=status)
