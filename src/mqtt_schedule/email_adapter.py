from __future__ import annotations

from dataclasses import dataclass, field
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import math
import smtplib
import ssl
from typing import Callable

from .notifications import EmailAttachment, EmailSendError, EmailSubmission


def validate_email_address(value: str) -> None:
    if not value or "\r" in value or "\n" in value:
        raise ValueError("Email addresses must be single plain addresses")
    try:
        address = Address(addr_spec=value)
    except (ValueError, HeaderParseError):
        raise ValueError("Email addresses must be single plain addresses") from None
    if not address.username or not address.domain or address.addr_spec != value:
        raise ValueError("Email addresses must include a mailbox and domain")


@dataclass(frozen=True)
class SmtpEmailSettings:
    sender_address: str = field(repr=False)
    password: str = field(repr=False)
    host: str = "smtp.gmail.com"
    port: int = 587
    timeout_seconds: float = 10


class SmtpEmailSender:
    def __init__(self, settings: SmtpEmailSettings, *, smtp_factory: Callable | None = None) -> None:
        validate_email_address(settings.sender_address)
        if not settings.password.strip():
            raise ValueError("Email password is required")
        if (not isinstance(settings.host, str) or not settings.host.strip()
                or any(character.isspace() for character in settings.host)):
            raise ValueError("SMTP host is invalid")
        if type(settings.port) is not int or not 1 <= settings.port <= 65535:
            raise ValueError("SMTP port is invalid")
        if (isinstance(settings.timeout_seconds, bool) or not isinstance(settings.timeout_seconds, (int, float))
                or not math.isfinite(settings.timeout_seconds) or settings.timeout_seconds <= 0):
            raise ValueError("SMTP timeout must be a positive finite number")
        self.settings = settings
        self._smtp_factory = smtp_factory or smtplib.SMTP

    def send(self, *, to_address: str, subject: str, body: str,
             attachments: tuple[EmailAttachment, ...] = ()) -> EmailSubmission:
        validate_email_address(to_address)
        message = EmailMessage()
        message["From"] = self.settings.sender_address
        message["To"] = to_address
        message["Subject"] = subject
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid()
        message.set_content(body)
        for attachment in attachments:
            if (not attachment.filename or any(char in attachment.filename for char in "\r\n/\\")):
                raise ValueError("Attachment filename must be a plain filename")
            message.add_attachment(attachment.content, maintype="application", subtype="gzip",
                                   filename=attachment.filename)
        try:
            with self._smtp_factory(self.settings.host, self.settings.port,
                                    timeout=self.settings.timeout_seconds) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                smtp.login(self.settings.sender_address, self.settings.password)
                refused = smtp.send_message(message, from_addr=self.settings.sender_address, to_addrs=[to_address])
                if refused:
                    raise EmailSendError("recipient_refused")
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailSendError("authentication_failed", smtp_code=exc.smtp_code) from None
        except smtplib.SMTPNotSupportedError:
            raise EmailSendError("smtp_feature_not_supported") from None
        except smtplib.SMTPRecipientsRefused:
            raise EmailSendError("recipient_refused") from None
        except smtplib.SMTPResponseException as exc:
            raise EmailSendError("smtp_rejected", smtp_code=exc.smtp_code) from None
        except (smtplib.SMTPException, OSError):
            # SMTP may have accepted DATA before the connection failed; do not resend automatically.
            raise EmailSendError("request_outcome_unknown") from None
        return EmailSubmission(message_id=str(message["Message-ID"]))
