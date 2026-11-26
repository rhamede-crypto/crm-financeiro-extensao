from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from adapters.persistence.probes import DatabaseHealthProbe
from adapters.queue.probes import RedisBrokerHealthProbe
from core.services.health import HealthService


class HealthDependencySerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    detail = serializers.CharField(allow_blank=True)


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "degraded"])
    dependencies = serializers.DictField(child=HealthDependencySerializer())


class HealthView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["Saúde"],
        summary="Verifica a disponibilidade da API, PostgreSQL e Redis",
        responses={200: HealthResponseSerializer, 503: HealthResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        service = HealthService(probes=[DatabaseHealthProbe(), RedisBrokerHealthProbe()])
        result = service.check()
        payload = {
            "status": "ok" if result.ok else "degraded",
            "dependencies": {
                dep.name: {"ok": dep.ok, "detail": dep.detail}
                for dep in result.dependencies
            },
        }
        return Response(
            payload,
            status=status.HTTP_200_OK if result.ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
