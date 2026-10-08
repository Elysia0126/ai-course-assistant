"""Outgoing email behind a small interface, so delivery is swappable and testable.

- ``smtp``     real delivery (STARTTLS or implicit TLS), the only option allowed in production
- ``outbox``   development: each message is written as an .eml file you can open in any mail client
- ``memory``   tests: messages are kept on the instance (FakeMailer)
- ``disabled`` password reset is switched off; the endpoint answers 503 instead of pretending to send
"""

import logging
import smtplib
import ssl
import threading
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Protocol

from app.core.config import Settings
from app.db.types import utcnow

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None


class Mailer(Protocol):
    name: str

    def send(self, message: EmailMessage) -> None: ...


def _to_mime(message: EmailMessage, sender: str) -> MimeMessage:
    mime = MimeMessage()
    mime["From"] = sender
    mime["To"] = message.to
    mime["Subject"] = message.subject
    mime["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1].strip(">") or None)
    mime.set_content(message.text)
    if message.html:
        mime.add_alternative(message.html, subtype="html")
    return mime


class SMTPMailer:
    name = "smtp"

    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, message: EmailMessage) -> None:
        s = self.settings
        context = ssl.create_default_context()
        smtp_class = smtplib.SMTP_SSL if s.smtp_ssl else smtplib.SMTP
        kwargs = {"context": context} if s.smtp_ssl else {}
        with smtp_class(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, **kwargs) as smtp:  # type: ignore[arg-type]
            if s.smtp_starttls:
                smtp.starttls(context=context)
            if s.smtp_username:
                password = s.smtp_password.get_secret_value() if s.smtp_password else ""
                smtp.login(s.smtp_username, password)
            smtp.send_message(_to_mime(message, s.smtp_from or ""))
        logger.info("Sent '%s' email via SMTP", message.subject)


class OutboxMailer:
    """Development inbox: messages land in MAIL_OUTBOX_DIR as .eml files (never used in production)."""

    name = "outbox"

    def __init__(self, settings: Settings):
        self.directory = Path(settings.mail_outbox_dir)
        self.sender = settings.smtp_from or "AI Course Assistant <no-reply@localhost>"

    def send(self, message: EmailMessage) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%dT%H%M%S%f")
        path = self.directory / f"{stamp}.eml"
        path.write_bytes(bytes(_to_mime(message, self.sender)))
        logger.info("Wrote '%s' email to the development outbox: %s", message.subject, path.name)


class MemoryMailer:
    """Test double: keeps every message in ``messages``."""

    name = "memory"

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []
        self._lock = threading.Lock()

    def send(self, message: EmailMessage) -> None:
        with self._lock:
            self.messages.append(message)


class DisabledMailer:
    name = "disabled"

    def send(self, message: EmailMessage) -> None:
        raise RuntimeError("Email delivery is disabled (MAIL_BACKEND=disabled).")


def build_mailer(settings: Settings) -> Mailer:
    match settings.mail_backend:
        case "smtp":
            return SMTPMailer(settings)
        case "outbox":
            return OutboxMailer(settings)
        case "memory":
            return MemoryMailer()
        case _:
            return DisabledMailer()


def password_reset_email(settings: Settings, to: str, token: str) -> EmailMessage:
    # The token travels in the URL fragment: browsers never send it to any server or put it in Referer.
    link = f"{settings.app_public_url}/reset-password#token={token}"
    minutes = settings.password_reset_ttl_seconds // 60
    text = (
        f"Someone (hopefully you) asked to reset the password for your {settings.app_name} account.\n\n"
        f"Choose a new password here (the link works once and expires in {minutes} minutes):\n{link}\n\n"
        "If you didn't ask for this, you can ignore this email — your password stays the same.\n"
    )
    html = (
        f"<p>Someone (hopefully you) asked to reset the password for your {settings.app_name} account.</p>"
        f'<p><a href="{link}">Choose a new password</a> — the link works once and expires in {minutes} minutes.</p>'
        "<p>If you didn't ask for this, you can ignore this email; your password stays the same.</p>"
    )
    return EmailMessage(to=to, subject=f"Reset your {settings.app_name} password", text=text, html=html)


def deliver(mailer: Mailer, message: EmailMessage) -> None:
    """Background-task wrapper: delivery failures are logged (without the link), never shown to the requester."""
    try:
        mailer.send(message)
    except Exception as exc:
        logger.error("Could not deliver '%s' email: %s", message.subject, type(exc).__name__)
