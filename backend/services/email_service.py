"""
Archmorph Email Service — sends session-ready notifications via Azure Communication Services.

Uses azure-communication-email SDK to send emails when background IaC + HLD
generation completes.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

ACS_CONNECTION_STRING = os.getenv("ACS_CONNECTION_STRING", "")
ACS_SENDER_EMAIL = os.getenv("ACS_SENDER_EMAIL", "")

_SITE_URL = os.getenv("ARCHMORPH_SITE_URL", "https://archmorph.com")


def is_email_configured() -> bool:
    """Check if email sending is configured."""
    return bool(ACS_CONNECTION_STRING and ACS_SENDER_EMAIL)


def send_session_ready_email(
    recipient_email: str,
    diagram_id: str,
    diagram_name: Optional[str] = None,
) -> bool:
    """Send a session-ready notification email.

    Parameters
    ----------
    recipient_email : str
        The user's email address.
    diagram_id : str
        The session/diagram ID to include in the link.
    diagram_name : str, optional
        Human-readable name for the architecture.

    Returns
    -------
    bool
        True if sent successfully, False otherwise.
    """
    if not is_email_configured():
        logger.warning("Email not configured — skipping notification for %s", diagram_id)
        return False

    try:
        from azure.communication.email import EmailClient

        client = EmailClient.from_connection_string(ACS_CONNECTION_STRING)

        session_url = f"{_SITE_URL}/#translator?session={diagram_id}"
        arch_name = diagram_name or "your architecture"

        message = {
            "senderAddress": ACS_SENDER_EMAIL,
            "recipients": {
                "to": [{"address": recipient_email}],
            },
            "content": {
                "subject": "Archmorph — Your migration outputs are ready",
                "html": f"""
                <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 32px 24px; background: #f8fafc;">
                  <div style="background: white; border-radius: 12px; padding: 32px; border: 1px solid #e2e8f0;">
                    <div style="text-align: center; margin-bottom: 24px;">
                      <span style="font-size: 28px; font-weight: 800; color: #0f172a;">Arch</span><span style="font-size: 28px; font-weight: 800; color: #22c55e;">morph</span>
                    </div>
                    <h2 style="color: #0f172a; font-size: 20px; margin: 0 0 12px;">Your migration outputs are ready</h2>
                    <p style="color: #64748b; font-size: 14px; line-height: 1.6; margin: 0 0 24px;">
                      The Terraform code and High-Level Design document for <strong>{arch_name}</strong> have been generated successfully.
                    </p>
                    <div style="text-align: center; margin: 24px 0;">
                      <a href="{session_url}" style="display: inline-block; background: #22c55e; color: white; text-decoration: none; padding: 12px 32px; border-radius: 8px; font-weight: 600; font-size: 14px;">
                        Open Your Session
                      </a>
                    </div>
                    <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 24px 0 0;">
                      This is an automated notification from Archmorph. Your session data is temporary and will expire after 2 hours.
                    </p>
                  </div>
                </div>
                """,
                "plainText": f"Your Archmorph migration outputs for {arch_name} are ready. Open your session: {session_url}",
            },
        }

        poller = client.begin_send(message)
        result = poller.result()
        logger.info("Email sent to %s for diagram %s (id=%s)", recipient_email, diagram_id, result.id)
        return True

    except Exception as exc:
        logger.error("Failed to send email to %s: %s", recipient_email, exc)
        return False
