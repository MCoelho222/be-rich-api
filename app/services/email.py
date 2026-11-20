"""Transactional email (specs/auth.md §7).

Senders are swappable behind `EmailSender`. Emails are sent after the database
transaction commits; callers decide how a failure is handled.
"""

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from functools import lru_cache
from html import escape
from typing import Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


class EmailError(Exception):
    pass


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailSender:
    """Development fallback: logs the email instead of sending it."""

    def send(self, message: EmailMessage) -> None:
        logger.info("Email to %s: %s\n%s", message.to, message.subject, message.text)


class SmtpEmailSender:
    """Plain SMTP, used with Mailpit in development (specs/operations.md §7)."""

    def __init__(self, host: str, port: int, sender: str) -> None:
        self.host, self.port, self.sender = host, port, sender

    def send(self, message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"], mime["To"], mime["Subject"] = self.sender, message.to, message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        try:
            with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
                smtp.send_message(mime)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailError(str(exc)) from exc


class ResendEmailSender:
    URL = "https://api.resend.com/emails"

    def __init__(self, api_key: str, sender: str) -> None:
        self.api_key, self.sender = api_key, sender

    def send(self, message: EmailMessage) -> None:
        try:
            response = httpx.post(
                self.URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "from": self.sender,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.text,
                    "html": message.html,
                },
                timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmailError(str(exc)) from exc


@lru_cache
def get_email_sender() -> EmailSender:
    """FastAPI dependency; overridden in tests."""
    settings = get_settings()
    if settings.email_backend == "resend":
        if not settings.resend_api_key:
            raise RuntimeError("EMAIL_BACKEND=resend requires RESEND_API_KEY")
        return ResendEmailSender(settings.resend_api_key, settings.email_from)
    if settings.email_backend == "smtp":
        return SmtpEmailSender(settings.smtp_host, settings.smtp_port, settings.email_from)
    return ConsoleEmailSender()


def send_quietly(sender: EmailSender, message: EmailMessage) -> bool:
    """Send, logging (not raising) failures. Returns whether the email was sent."""
    try:
        sender.send(message)
        return True
    except EmailError:
        logger.exception("Failed to send '%s' email", message.subject)
        return False


# --- Templates (pt-BR, plain text + HTML) ----------------------------------------


def _html(paragraphs: list[str], link: str | None = None) -> str:
    body = "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    if link:
        body += f'<p><a href="{escape(link)}">{escape(link)}</a></p>'
    return f"<!doctype html><html><body>{body}</body></html>"


def first_name(name: str) -> str:
    return name.strip().split()[0] if name.strip() else name


def invitation_email(
    to: str, inviter_name: str, household_name: str, expires_on: str, link: str
) -> EmailMessage:
    lines = [
        f"{first_name(inviter_name)} convidou você para participar de \"{household_name}\" no Be Rich.",
        f"O convite é válido até {expires_on}.",
    ]
    return EmailMessage(
        to=to,
        subject=f"Convite para {household_name} no Be Rich",
        text="\n\n".join([*lines, f"Aceite o convite: {link}"]),
        html=_html(lines, link),
    )


def password_reset_email(to: str, name: str, link: str) -> EmailMessage:
    lines = [
        f"Olá, {first_name(name)}.",
        "Recebemos um pedido para redefinir a sua senha. O link abaixo vale por 1 hora e só pode ser usado uma vez.",
        "Se você não pediu isso, ignore este email.",
    ]
    return EmailMessage(
        to=to,
        subject="Redefinição de senha do Be Rich",
        text="\n\n".join([*lines, link]),
        html=_html(lines, link),
    )


def password_changed_email(to: str, name: str, when: str) -> EmailMessage:
    lines = [
        f"Olá, {first_name(name)}.",
        f"A sua senha do Be Rich foi alterada em {when}.",
        "Se não foi você, redefina a sua senha imediatamente.",
    ]
    return EmailMessage(
        to=to, subject="Sua senha do Be Rich foi alterada", text="\n\n".join(lines), html=_html(lines)
    )
