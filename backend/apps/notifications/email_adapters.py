"""
Email senders. No Django / MongoDB imports.

 * SmtpEmailAdapter: any SMTP server (use a test inbox such as Mailtrap while developing). Never sends to a number or
   address it has not been given by the worker; header injection is impossible because EmailMessage rejects newlines.
 * ConsoleEmailAdapter: prints the email to the server log. Refused unless DEBUG=True (see deps).
 * There is NO SMS provider. SMS is not implemented.
"""
import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class EmailError(Exception):
    def __init__(self, message: str, permanent: bool = False):
        super().__init__(message)
        self.permanent = permanent


class EmailAdapter(ABC):
    name = "base"

    @abstractmethod
    def send(self, to: str, subject: str, text: str) -> None:
        """Send one plain-text email or raise EmailError (permanent=True: do not retry)."""


class ConsoleEmailAdapter(EmailAdapter):
    name = "console"

    def send(self, to, subject, text):
        logger.info("EMAIL (console, not really sent) to=%s subject=%s\n%s", to, subject, text)


class SmtpEmailAdapter(EmailAdapter):
    name = "smtp"

    def __init__(self, host, port, username, password, sender, use_tls=True, timeout=15, smtp_factory=None):
        self.host, self.port, self.username, self.password = host, port, username, password
        self.sender, self.use_tls, self.timeout = sender, use_tls, timeout
        self._factory = smtp_factory or (lambda: smtplib.SMTP(host, port, timeout=timeout))

    def send(self, to, subject, text):
        try:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
            msg.set_content(text)
        except (ValueError, TypeError) as exc:      # newline in an address, etc.: retrying cannot help
            raise EmailError("The message could not be built.", permanent=True) from exc
        try:
            with self._factory() as smtp:
                if self.use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                if self.username:
                    smtp.login(self.username, self.password)
                smtp.send_message(msg)
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailError("The recipient address was refused.", permanent=True) from exc
        except smtplib.SMTPResponseException as exc:
            # 5xx = permanent, 4xx = try again later. Never put the server's text (may echo secrets) in our message.
            raise EmailError(f"SMTP error {exc.smtp_code}.", permanent=500 <= exc.smtp_code < 600 and exc.smtp_code != 535) from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailError(f"Could not reach the mail server ({type(exc).__name__}).") from exc
