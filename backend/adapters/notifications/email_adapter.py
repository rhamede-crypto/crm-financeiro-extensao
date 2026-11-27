from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import EmailMessage

from core.ports.notifications import DeliveryReceipt, NotificationMessage

logger = logging.getLogger(__name__)


class DjangoEmailNotificationAdapter:
    """SMTP email notification adapter implementing NotificationChannelPort."""

    def send(self, message: NotificationMessage) -> DeliveryReceipt:
        try:
            mail = EmailMessage(
                subject=message.subject,
                body=message.body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[message.recipient],
            )
            sent_count = mail.send(fail_silently=False)
            if sent_count:
                return DeliveryReceipt(status="sent", channel="email")
            return DeliveryReceipt(
                status="failed",
                channel="email",
                reason="smtp_zero_delivered",
            )
        except Exception as exc:
            logger.warning(
                "Notification delivery failed for company=%s channel=%s error=%s",
                message.company_id,
                message.channel,
                type(exc).__name__,
            )
            return DeliveryReceipt(
                status="failed",
                channel="email",
                reason=type(exc).__name__,
            )
