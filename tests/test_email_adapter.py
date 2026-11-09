from dataclasses import replace
import smtplib
import ssl

import pytest

from mqtt_schedule.email_adapter import SmtpEmailSender, SmtpEmailSettings
from mqtt_schedule.notifications import EmailSendError


SENDER = "sender@example.test"
RECIPIENT = "recipient@example.test"
PASSWORD = "test-only-email-password"


class FakeSMTP:
    def __init__(self, *, fail_at=None, error=None, refused=None):
        self.calls = []
        self.fail_at = fail_at
        self.error = error
        self.refused = refused or {}
        self.message = None

    def record(self, method, *args):
        self.calls.append((method, args))
        if self.fail_at == method:
            raise self.error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.record("close")

    def ehlo(self):
        self.record("ehlo")

    def starttls(self, *, context):
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
        self.record("starttls")

    def login(self, username, password):
        self.record("login", username, password)

    def send_message(self, message, *, from_addr, to_addrs):
        self.message = message
        self.record("send_message", from_addr, to_addrs)
        return self.refused


def settings() -> SmtpEmailSettings:
    return SmtpEmailSettings(sender_address=SENDER, password=PASSWORD)


def test_email_uses_verified_starttls_before_login_and_private_envelope() -> None:
    smtp = FakeSMTP()
    connections = []

    def connect(host, port, **kwargs):
        connections.append((host, port, kwargs))
        return smtp

    result = SmtpEmailSender(settings(), smtp_factory=connect).send(
        to_address=RECIPIENT, subject="Service started", body="Host: test-linux\nServer: 123",
    )

    assert connections == [("smtp.gmail.com", 587, {"timeout": 10})]
    assert [name for name, _ in smtp.calls] == ["ehlo", "starttls", "ehlo", "login", "send_message", "close"]
    assert smtp.calls[3] == ("login", (SENDER, PASSWORD))
    assert smtp.calls[4] == ("send_message", (SENDER, [RECIPIENT]))
    assert smtp.message["To"] == RECIPIENT
    assert smtp.message["From"] == SENDER
    assert smtp.message["Subject"] == "Service started"
    assert "test-linux" in smtp.message.get_content()
    assert PASSWORD not in smtp.message.as_string()
    assert result.message_id == str(smtp.message["Message-ID"])
    assert result.status == "accepted"


def test_smtp_without_starttls_never_receives_password() -> None:
    smtp = FakeSMTP(fail_at="starttls", error=smtplib.SMTPNotSupportedError("private provider error"))
    with pytest.raises(EmailSendError, match="smtp_feature_not_supported"):
        SmtpEmailSender(settings(), smtp_factory=lambda *a, **k: smtp).send(
            to_address=RECIPIENT, subject="Test", body="Test",
        )
    assert not any(name in {"login", "send_message"} for name, _ in smtp.calls)


@pytest.mark.parametrize("fail_at,error,reason,code", [
    ("login", smtplib.SMTPAuthenticationError(535, f"private {PASSWORD} {SENDER}".encode()), "authentication_failed", 535),
    ("send_message", smtplib.SMTPRecipientsRefused({RECIPIENT: (550, b"refused")}), "recipient_refused", None),
    ("send_message", smtplib.SMTPDataError(550, b"private provider error"), "smtp_rejected", 550),
    ("send_message", TimeoutError(f"private {PASSWORD}"), "request_outcome_unknown", None),
    ("close", smtplib.SMTPServerDisconnected(f"private {PASSWORD}"), "request_outcome_unknown", None),
])
def test_email_failure_is_sanitized_and_not_retried(fail_at, error, reason, code) -> None:
    smtp = FakeSMTP(fail_at=fail_at, error=error)
    connections = []

    def connect(*args, **kwargs):
        connections.append(args)
        return smtp

    with pytest.raises(EmailSendError) as caught:
        SmtpEmailSender(settings(), smtp_factory=connect).send(to_address=RECIPIENT, subject="Test", body="Test")
    assert caught.value.reason == reason
    assert caught.value.smtp_code == code
    assert len(connections) == 1
    assert sum(name == "send_message" for name, _ in smtp.calls) <= 1
    assert PASSWORD not in str(caught.value)
    assert SENDER not in str(caught.value)
    assert RECIPIENT not in str(caught.value)


def test_refused_recipient_result_is_not_logged_as_success() -> None:
    smtp = FakeSMTP(refused={RECIPIENT: (550, b"refused")})
    with pytest.raises(EmailSendError, match="recipient_refused"):
        SmtpEmailSender(settings(), smtp_factory=lambda *a, **k: smtp).send(
            to_address=RECIPIENT, subject="Test", body="Test",
        )


@pytest.mark.parametrize("recipient", ["bad", "name@", "@example.test", "name@example.test\nBcc: other@example.test"])
def test_invalid_email_recipient_never_opens_smtp(recipient) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid recipients must not open SMTP")

    with pytest.raises(ValueError):
        SmtpEmailSender(settings(), smtp_factory=forbidden).send(to_address=recipient, subject="Test", body="Test")


def test_email_subject_header_injection_never_opens_smtp() -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid headers must not open SMTP")

    with pytest.raises(ValueError):
        SmtpEmailSender(settings(), smtp_factory=forbidden).send(
            to_address=RECIPIENT, subject="Test\nBcc: other@example.test", body="Test",
        )


@pytest.mark.parametrize("changes", [{"port": 0}, {"port": 65536}, {"timeout_seconds": 0},
                                      {"timeout_seconds": float("inf")}, {"host": ""}])
def test_invalid_smtp_settings_are_rejected(changes) -> None:
    with pytest.raises(ValueError):
        SmtpEmailSender(replace(settings(), **changes))


def test_email_settings_repr_hides_credentials() -> None:
    assert SENDER not in repr(settings())
    assert PASSWORD not in repr(settings())
