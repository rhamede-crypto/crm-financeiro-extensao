from __future__ import annotations

from typing import Protocol
from uuid import UUID


class TaskQueuePort(Protocol):
    def enqueue_company_job(self, task_name: str, company_id: UUID, job_id: UUID) -> str:
        ...
