from __future__ import annotations

from django.db import connection

from core.domain.entities import HealthDependencyStatus


class DatabaseHealthProbe:
    def check(self) -> HealthDependencyStatus:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return HealthDependencyStatus(name="database", ok=True)
        except Exception:
            return HealthDependencyStatus(name="database", ok=False, detail="unavailable")
