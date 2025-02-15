import getpass
import smtplib
import socket
import logging
from email.message import EmailMessage
from email.mime.application import MIMEApplication
from email.utils import formatdate
from pathlib import Path
from smtplib import SMTPAuthenticationError, SMTPServerDisconnected, SMTPSenderRefused

from ..core import Provider, Response
from ..utils.schema.helpers import one_or_more, list_to_commas

DEFAULT_SUBJECT = "New email from 'notifiers'!"
DEFAULT_FROM = f"{getpass.getuser()}@{socket.getfqdn()}"
DEFAULT_SMTP_HOST = "localhost"

log = logging.getLogger(__file__)

class SMTP(Provider):
    """Send emails via SMTP"""

    base_url = None
    site_url = "https://en.wikipedia.org/wiki/Email"
    name = "email"

    _required = {"required": ["message", "to", "username", "password"]}

    _schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "title": "the content of the email message"},
            "subject": {"type": "string", "title": "the subject of the email message"},
            "to": one_or_more(
                {
                    "type": "string",
                    "format": "email",
                    "title": "one or more email addresses to use",
                }
            ),
            "from": {
                "type": "string",
                "format": "email",
                "title": "the FROM address to use in the email",
            },
            "from_": {
                "type": "string",
                "format": "email",
                "title": "the FROM address to use in the email",
                "duplicate": True,
            },
            "attachments": one_or_more(
                {
                    "type": "string",
                    "format": "valid_file",
                    "title": "one or more attachments to use in the email",
                }
            ),
            "host": {
                "type": "string",
                "format": "hostname",
                "title": "the host of the SMTP server",
            },
            "port": {
                "type": "integer",
                "format": "port",
                "title": "the port number to use",
            },
            "username": {"type": "string", "title": "username if relevant"},
            "password": {"type": "string", "title": "password if relevant"},
            "tls": {"type": "boolean", "title": "should TLS be used"},
            "ssl": {"type": "boolean", "title": "should SSL be used"},
            "html": {
                "type": "boolean",
                "title": "should the email be parse as an HTML file",
            },
        },
        "dependencies": {
            "username": ["password"],
            "password": ["username"],
            "ssl": ["tls"],
        },
        "additionalProperties": False,
    }

    def __init__(self):
        super().__init__()
        self.smtp_server = None
        self.configuration = None

    @property
    def defaults(self) -> dict:
        return {
            "subject": DEFAULT_SUBJECT,
            "from": DEFAULT_FROM,
            "host": DEFAULT_SMTP_HOST,
            "port": 25,
            "tls": False,
            "ssl": False,
            "html": False,
        }

    def _prepare_data(self, data: dict) -> dict:
        if isinstance(data["to"], list):
            data["to"] = list_to_commas(data["to"])
        # A workaround since `from` is a reserved word
        if data.get("from_"):
            data["from"] = data.pop("from_")
        return data

    @staticmethod
    def _build_email(data: dict) -> EmailMessage:
        email = EmailMessage()
        email["To"] = data["to"]
        email["From"] = data["from"]
        email["Subject"] = data["subject"]
        email["Date"] = formatdate(localtime=True)
        content_type = "html" if data["html"] else "plain"
        email.add_alternative(data["message"], subtype=content_type)
        return email

    @staticmethod
    def _add_attachments(data: dict, email: EmailMessage) -> EmailMessage:
        for attachment in data["attachments"]:
            file = Path(attachment).read_bytes()
            part = MIMEApplication(file)
            part.add_header("Content-Disposition", "attachment", filename=attachment)
            email.attach(part)
        return email

    def _connect_to_server(self, data: dict):
        self.smtp_server = smtplib.SMTP_SSL if data["ssl"] else smtplib.SMTP
        log.debug('pre smtp client init')
        self.smtp_server = self.smtp_server()
        self.smtp_server.set_debuglevel(True)
        self.smtp_server.connect(data["host"], data["port"])
        self.configuration = self._get_configuration(data)
        log.debug('pre handshake')
        if data["tls"] and not data["ssl"]:
            self.smtp_server.ehlo()
            self.smtp_server.starttls()

        log.debug('pre auth')
        if data.get("username"):
            self.smtp_server.login(data["username"], data["password"])

    @staticmethod
    def _get_configuration(data: dict) -> tuple:
        return data["host"], data["port"], data.get("username")

    def _send_notification(self, data: dict) -> Response:
        errors = None
        try:
            configuration = self._get_configuration(data)
            log.debug('CNFG - {0}'.format(configuration))
            if (
                not self.configuration
                or not self.smtp_server
                or self.configuration != configuration
            ):
                self._connect_to_server(data)
            log.debug('connected')
            email = self._build_email(data)
            log.debug('mail built')
            if data.get("attachments"):
                email = self._add_attachments(data, email)
            self.smtp_server.send_message(email)
            log.debug('mail sent')
        except (
            SMTPServerDisconnected,
            SMTPSenderRefused,
            socket.error,
            OSError,
            IOError,
            SMTPAuthenticationError,
        ) as e:
            errors = [str(e)]
        return self.create_response(data, errors=errors)
