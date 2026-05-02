"""Email sending via SMTP — configured through environment variables.

Required env vars (all optional with defaults):
  SMTP_HOST      default: localhost
  SMTP_PORT      default: 587
  SMTP_USER      default: (empty, no auth)
  SMTP_PASSWORD  default: (empty, no auth)
  SMTP_FROM      default: noreply@patrimonium.local
  APP_URL        default: http://localhost:5173
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "noreply@patrimonium.local")
APP_URL = os.getenv("APP_URL", "http://localhost:5173")


def _send(to: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.ehlo()
        if smtp.has_extn("STARTTLS"):
            smtp.starttls()
            smtp.ehlo()
        if SMTP_USER and SMTP_PASSWORD:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.sendmail(SMTP_FROM, [to], msg.as_string())


def send_password_reset(to: str, token: str) -> None:
    link = f"{APP_URL}/reset-password?token={token}"
    html = f"""
    <p>Bonjour,</p>
    <p>Vous avez demandé la réinitialisation de votre mot de passe Patrimonium.</p>
    <p><a href="{link}">Cliquez ici pour définir un nouveau mot de passe</a></p>
    <p>Ce lien est valide pendant <strong>1 heure</strong>.</p>
    <p>Si vous n'avez pas effectué cette demande, ignorez cet e-mail.</p>
    """
    try:
        _send(to, "Réinitialisation de mot de passe — Patrimonium", html)
        logger.info(f"Password reset email sent to {to}")
    except Exception as e:
        logger.error(f"Failed to send password reset email to {to}: {e}")
        raise
