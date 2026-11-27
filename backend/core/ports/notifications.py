from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    company_id: UUID
    recipient: str
    subject: str
    body: str
    channel: str = "email"


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    status: str
    channel: str
    provider_reference: str = ""
    reason: str = ""


class NotificationChannelPort(Protocol):
    def send(self, message: NotificationMessage) -> DeliveryReceipt:
        ...
