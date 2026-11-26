from __future__ import annotations

import redis
from django.conf import settings

from core.domain.entities import HealthDependencyStatus


class RedisBrokerHealthProbe:
    def check(self) -> HealthDependencyStatus:
        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            return HealthDependencyStatus(name="broker", ok=True, detail="eager")
        try:
            client = redis.Redis.from_url(
                settings.CELERY_BROKER_URL,
                socket_connect_timeout=1.5,
                socket_timeout=1.5,
            )
            client.ping()
            return HealthDependencyStatus(name="broker", ok=True)
        except Exception:
            return HealthDependencyStatus(name="broker", ok=False, detail="unavailable")
