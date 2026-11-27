from __future__ import annotations

from uuid import UUID

from celery import current_app
from django.conf import settings


class ScopedCeleryDispatcher:
    """Enforces explicit company_id propagation when enqueuing background jobs."""

    def enqueue_company_job(self, task_name: str, company_id: UUID, job_id: UUID) -> str:
        args = [str(company_id), str(job_id)]
        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            import adapters.queue.tasks  # noqa: F401

            task = current_app.tasks.get(task_name)
            if task is not None:
                result = task.apply(args=args)
                return str(result.id or "")

        result = current_app.send_task(task_name, args=args)
        return str(result.id or "")
