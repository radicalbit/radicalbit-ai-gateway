import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from radicalbit_ai_gateway.utils.app_config import get_app_config

app_config = get_app_config()
logger = logging.getLogger(app_config.log_config.logger_name)


class EmailService:
    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
        from_email: str | None = None,
    ):
        cfg = app_config.smtp_config
        self.smtp_host = smtp_host or cfg.smtp_host
        self.smtp_port = smtp_port or cfg.smtp_port
        self.smtp_user = smtp_user or cfg.smtp_user
        self.smtp_password = smtp_password or cfg.smtp_password
        self.from_email = from_email or cfg.smtp_from_email

    def send_email(self, recipients: list[str], subject: str, body: str) -> bool:
        if not recipients:
            logger.info('No email recipients specified for notification.')
            return False

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.from_email
        msg['To'] = ', '.join(recipients)

        part = MIMEText(body, 'html' if ('<' in body and '>' in body) else 'plain')
        msg.attach(part)

        try:
            with smtplib.SMTP(self.smtp_host, int(self.smtp_port), timeout=10) as server:
                if self.smtp_user and self.smtp_password:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_email, recipients, msg.as_string())
            logger.info('Successfully dispatched alert email notification to %s', recipients)
            return True
        except Exception as e:
            logger.warning(
                'Failed to send alert email notification to %s via SMTP (%s:%s): %s',
                recipients,
                self.smtp_host,
                self.smtp_port,
                e,
            )
            return False
