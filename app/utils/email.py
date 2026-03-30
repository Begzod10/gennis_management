import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from ..config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str):
    if not settings.SMTP_USER or not to:
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
        msg["To"] = to
        msg.attach(MIMEText(body, "html"))
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.sendmail(msg["From"], to, msg.as_string())
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")


def notify_mission_assigned(email: str, name: str, title: str, deadline, description: str):
    subject = f"Yangi topshiriq: {title}"
    body = f"""
    <p>Salom, <b>{name}</b>!</p>
    <p>Sizga yangi topshiriq yuklandi:</p>
    <ul>
      <li><b>Nomi:</b> {title}</li>
      <li><b>Muddati:</b> {deadline or '—'}</li>
      <li><b>Tavsif:</b> {description or '—'}</li>
    </ul>
    """
    send_email(email, subject, body)


def notify_mission_status_changed(email: str, name: str, title: str, new_status: str):
    subject = f"Topshiriq holati o'zgardi: {title}"
    body = f"""
    <p>Salom, <b>{name}</b>!</p>
    <p><b>{title}</b> topshirig'ingiz holati <b>{new_status}</b> ga o'zgartirildi.</p>
    """
    send_email(email, subject, body)
