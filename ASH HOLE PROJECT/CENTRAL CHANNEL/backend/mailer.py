"""SMTP delivery for guest support reports and administrator replies."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from . import config


class MailDeliveryError(Exception):
    """Raised when server-side SMTP settings or delivery are unavailable."""


def send_hotel_email(recipient: str, subject: str, body: str, reply_to: str = "") -> None:
    if not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
        raise MailDeliveryError(
            "Email delivery is not configured. Set CENTRAL_SMTP_USERNAME and CENTRAL_SMTP_PASSWORD."
        )

    username = config.SMTP_USERNAME.strip()
    password = "".join(config.SMTP_PASSWORD.split())
    message = EmailMessage()
    message["From"] = formataddr(("NEXORA Hotel", config.SMTP_SENDER))
    message["To"] = recipient
    message["Subject"] = subject
    if reply_to:
        message["Reply-To"] = reply_to
    message.set_content(body)

    try:
        if config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(
                config.SMTP_HOST,
                config.SMTP_PORT,
                timeout=15,
                context=ssl.create_default_context(),
            ) as smtp:
                smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                smtp.login(username, password)
                smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise MailDeliveryError("The email service could not deliver the message.") from error
