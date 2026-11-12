"""Outgoing mail: SMTP for hosting, a logging mailer for development."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from loguru import logger

from previewit.application.ports import MailError


class LogMailer:
    """Development default: print the mail instead of sending it."""

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("MAIL to={} subject={}\n{}", to, subject, body)


class SmtpMailer:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        sender: str,
        security: str = "starttls",
    ) -> None:
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._sender = sender
        self._security = security

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        try:
            message["From"] = self._sender
            message["To"] = to
            message["Subject"] = subject
        except ValueError as error:  # header injection (newlines) is refused by the email package
            raise MailError(str(error)) from error
        message["Message-ID"] = make_msgid(domain=self._sender.rsplit("@", 1)[-1].strip("> "))
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(body)
        try:
            context = ssl.create_default_context()
            if self._security == "ssl":
                with smtplib.SMTP_SSL(self._host, self._port, timeout=15, context=context) as smtp:
                    self._deliver(smtp, message)
            else:
                with smtplib.SMTP(self._host, self._port, timeout=15) as smtp:
                    if self._security == "starttls":
                        smtp.starttls(context=context)
                    self._deliver(smtp, message)
        except (smtplib.SMTPException, OSError) as error:
            raise MailError(str(error)) from error

    def _deliver(self, smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if self._username and self._password:
            smtp.login(self._username, self._password)
        smtp.send_message(message)
