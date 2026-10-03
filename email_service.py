"""Enterprise Email Delivery Service for OpsFlow SaaS Platform.

Supports:
- Production SMTP delivery (TLS/STARTTLS) using standard environment variables:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, APP_BASE_URL
- Safe offline / development mock delivery when SMTP credentials are not configured
- Zero credential exposure in logs or audit records
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

logger = logging.getLogger("opsflow.email")


def is_smtp_configured() -> bool:
    """Checks whether valid production SMTP credentials are provided."""
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASSWORD", "").strip()
    return bool(host and user and password and not host.startswith("smtp.example"))


def send_password_reset_email(
    to_email: str,
    reset_token: str,
    user_name: Optional[str] = None
) -> Dict[str, Any]:
    """Dispatches a password reset email via SMTP or safe development mock."""
    base_url = os.environ.get("APP_BASE_URL", "http://localhost:5000").rstrip("/")
    reset_url = f"{base_url}/#reset-token={reset_token}"
    display_name = user_name or to_email.split("@")[0]

    subject = "OpsFlow Cloud - Reset Your Account Password"

    text_body = (
        f"Hello {display_name},\n\n"
        f"A password reset request was received for your OpsFlow Cloud account ({to_email}).\n\n"
        f"To set a new password, click the link below or paste it into your browser:\n"
        f"{reset_url}\n\n"
        f"Security Notice:\n"
        f"- This link is valid for 1 hour only.\n"
        f"- This link can be used exactly once.\n"
        f"- If you did not request this reset, your account remains secure and no action is required.\n\n"
        f"OpsFlow Cloud Security Team\n"
    )

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background:#0f172a; color:#f8fafc; padding:24px;">
        <div style="max-width:560px; margin:0 auto; background:#1e293b; border:1px solid #334155; border-radius:8px; padding:32px;">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:20px;">
                <span style="font-size:24px;">⚡</span>
                <h2 style="color:#00f0ff; margin:0; font-size:20px; letter-spacing:1px;">OPSFLOW CLOUD</h2>
            </div>
            <h3 style="color:#f8fafc; margin-top:0;">Password Reset Request</h3>
            <p style="color:#94a3b8; font-size:14px; line-height:1.6;">
                Hello <strong>{display_name}</strong>, a request has been received to reset the password for <code>{to_email}</code>.
            </p>
            <div style="margin:28px 0; text-align:center;">
                <a href="{reset_url}" style="background:#00f0ff; color:#0f172a; padding:12px 24px; border-radius:6px; font-weight:700; text-decoration:none; display:inline-block; font-size:14px;">
                    Reset Password
                </a>
            </div>
            <p style="color:#64748b; font-size:12px; line-height:1.5;">
                This link expires in <strong>1 hour</strong> and can only be used once.<br>
                If you did not request this change, you can safely ignore this email.
            </p>
            <hr style="border:none; border-top:1px solid #334155; margin:24px 0;">
            <p style="color:#475569; font-size:11px; margin:0;">OpsFlow Enterprise Automation Platform • Automated Security Notification</p>
        </div>
    </body>
    </html>
    """

    if is_smtp_configured():
        smtp_host = os.environ.get("SMTP_HOST", "")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_password = os.environ.get("SMTP_PASSWORD", "")
        smtp_from = os.environ.get("SMTP_FROM", "noreply@opsflow.io")

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = smtp_from
            msg["To"] = to_email

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_from, [to_email], msg.as_string())

            logger.info("Successfully dispatched password reset email via SMTP to %s", to_email)
            return {
                "sent": True,
                "method": "smtp",
                "recipient": to_email
            }
        except Exception as exc:
            logger.error("Failed to send password reset email via SMTP: %s", exc)
            return {
                "sent": False,
                "method": "smtp",
                "error": str(exc),
                "recipient": to_email
            }

    # Safe development mock mode
    logger.info("[DEV EMAIL DISPATCH] Password reset for %s. Reset link: %s", to_email, reset_url)
    return {
        "sent": True,
        "method": "mock_development",
        "recipient": to_email,
        "reset_url": reset_url,
        "notice": "SMTP not configured; simulated email dispatch recorded safely."
    }
