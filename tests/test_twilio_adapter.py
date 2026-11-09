from dataclasses import dataclass

import pytest
import requests

from mqtt_schedule.notifications import SmsSendError
from mqtt_schedule.twilio_adapter import TwilioSmsSender, TwilioSmsSettings


ACCOUNT_SID = "AC" + "0" * 32
MESSAGE_SID = "SM" + "1" * 32
AUTH_TOKEN = "test-only-private-token"
FROM_NUMBER = "+15550001111"
TO_NUMBER = "+15550002222"


@dataclass
class FakeResponse:
    status_code: int
    payload: object

    def json(self):
        if isinstance(self.payload, ValueError):
            raise self.payload
        return self.payload


def settings() -> TwilioSmsSettings:
    return TwilioSmsSettings(account_sid=ACCOUNT_SID, auth_token=AUTH_TOKEN, from_number=FROM_NUMBER)


def test_twilio_submission_uses_authenticated_form_and_timeouts() -> None:
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse(201, {"sid": MESSAGE_SID, "status": "queued"})

    result = TwilioSmsSender(settings(), post=post).send(to_number=TO_NUMBER, body="Service started")

    assert result.message_sid == MESSAGE_SID
    assert result.status == "queued"
    assert calls == [(
        f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT_SID}/Messages.json",
        {
            "auth": (ACCOUNT_SID, AUTH_TOKEN),
            "data": {"From": FROM_NUMBER, "To": TO_NUMBER, "Body": "Service started"},
            "timeout": (5, 10),
            "allow_redirects": False,
        },
    )]


@pytest.mark.parametrize("status", [301, 400, 401, 429, 500])
def test_twilio_http_failure_is_redacted_and_not_retried(status: int) -> None:
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs)
        return FakeResponse(status, {"code": 20003, "message": f"private {AUTH_TOKEN} {TO_NUMBER}"})

    with pytest.raises(SmsSendError) as caught:
        TwilioSmsSender(settings(), post=post).send(to_number=TO_NUMBER, body="Service started")

    assert len(calls) == 1
    assert caught.value.http_status == status
    assert caught.value.provider_code == 20003
    assert AUTH_TOKEN not in str(caught.value)
    assert TO_NUMBER not in str(caught.value)


def test_twilio_timeout_does_not_resend_or_expose_request() -> None:
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs)
        raise requests.Timeout(f"private {AUTH_TOKEN} {TO_NUMBER}")

    with pytest.raises(SmsSendError, match="request_outcome_unknown") as caught:
        TwilioSmsSender(settings(), post=post).send(to_number=TO_NUMBER, body="Service started")

    assert len(calls) == 1
    assert AUTH_TOKEN not in str(caught.value)
    assert TO_NUMBER not in str(caught.value)


@pytest.mark.parametrize("payload", [
    {}, [], ValueError("bad JSON"),
    {"sid": MESSAGE_SID, "status": []},
    {"sid": "invalid", "status": "queued"},
    {"sid": MESSAGE_SID, "status": "private-unexpected-status"},
])
def test_twilio_invalid_success_payload_is_reported(payload) -> None:
    sender = TwilioSmsSender(settings(), post=lambda *a, **k: FakeResponse(201, payload))
    with pytest.raises(SmsSendError, match="invalid_submission_response"):
        sender.send(to_number=TO_NUMBER, body="Service started")


def test_twilio_invalid_recipient_never_calls_http() -> None:
    def post(*args, **kwargs):
        pytest.fail("Invalid recipients must not trigger an HTTP request")

    with pytest.raises(ValueError, match="E.164"):
        TwilioSmsSender(settings(), post=post).send(to_number="5550002222", body="Service started")


def test_twilio_settings_repr_does_not_expose_credentials_or_phone() -> None:
    value = repr(settings())
    assert ACCOUNT_SID not in value
    assert AUTH_TOKEN not in value
    assert FROM_NUMBER not in value
