import logging
import smtplib
from email.message import EmailMessage
from typing import ClassVar

import pytest

from previewit.adapters.mail import LogMailer, SmtpMailer
from previewit.adapters.settings import Settings
from previewit.application.ports import MailError


class FakeSmtp:
    instances: ClassVar[list["FakeSmtp"]] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host, self.port = host, port
        self.calls: list[str] = []
        self.message: EmailMessage | None = None
        FakeSmtp.instances.append(self)

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def starttls(self, **_: object) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, message: EmailMessage) -> None:
        self.message = message


def test_smtp_mailer_starttls_login_and_message(monkeypatch: pytest.MonkeyPatch):
    FakeSmtp.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    mailer = SmtpMailer("smtp.example", 587, "user", "pw", "Previewit <no-reply@prreview.example>")
    mailer.send("ann@x.fi", "Hello", "Body")
    smtp = FakeSmtp.instances[0]
    assert smtp.message is not None
    assert smtp.calls == ["starttls", "login:user"]
    assert smtp.message["To"] == "ann@x.fi"
    assert smtp.message["Subject"] == "Hello"
    assert smtp.message["From"] == "Previewit <no-reply@prreview.example>"
    assert smtp.message["Auto-Submitted"] == "auto-generated"
    assert smtp.message.get_content().strip() == "Body"


def test_smtp_failures_become_mail_errors(monkeypatch: pytest.MonkeyPatch):
    def refuse(*_a: object, **_k: object) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    with pytest.raises(MailError):
        SmtpMailer("h", 587, None, None, "a@b.fi").send("x@y.fi", "s", "b")


def test_header_injection_is_refused():
    with pytest.raises(MailError):
        SmtpMailer("h", 587, None, None, "a@b.fi").send("x@y.fi\nBcc: evil@z.fi", "s", "b")


def test_log_mailer_prints_the_mail_for_development(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO):
        LogMailer().send("ann@x.fi", "Subject", "link: http://localhost/verify?token=abc")
    assert "ann@x.fi" in caplog.text and "token=abc" in caplog.text


def test_settings_read_the_smtp_variables():
    s = Settings.from_env(
        {
            "PREVIEWIT_SMTP_HOST": "smtp.example",
            "PREVIEWIT_SMTP_PORT": "465",
            "PREVIEWIT_SMTP_SECURITY": "ssl",
            "PREVIEWIT_MAIL_FROM": "a@b.fi",
        }
    )
    assert (s.smtp_host, s.smtp_port, s.smtp_security, s.mail_from) == (
        "smtp.example",
        465,
        "ssl",
        "a@b.fi",
    )
    assert Settings.from_env({}).smtp_port == 587
