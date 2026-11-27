from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import yaml
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularSwaggerView
from rest_framework import renderers, serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from adapters.persistence.models import ImportJobRecord, StoredImportFile
from adapters.persistence.probes import DatabaseHealthProbe
from adapters.persistence.repositories import DjangoCompanyScopeRepository
from adapters.queue.celery_dispatcher import ScopedCeleryDispatcher
from adapters.queue.probes import RedisBrokerHealthProbe
from adapters.storage.local_storage import TenantLocalFileStorage
from core.domain.exceptions import (
    AuthenticationDomainError,
    PayloadTooLargeError,
    ResourceNotFoundError,
    StateConflictError,
)
from core.domain.value_objects import ImportStatus
from core.services.health import HealthService

from .idempotency import run_idempotent, tenant_storage_path
from .permissions import HasCompanyScope
from .serializers import ImportCreateSerializer, ImportJobSerializer

CONTRACT_PATH = Path(settings.BASE_DIR) / "contracts" / "openapi.v1.yaml"


def _load_openapi_contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


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


class OpenAPIJSONRenderer(JSONRenderer):
    media_type = "application/vnd.oai.openapi+json"
    format = "json"


class OpenAPIYAMLRenderer(renderers.BaseRenderer):
    media_type = "application/vnd.oai.openapi"
    format = "yaml"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, (bytes, str)):
            return data
        return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


class OpenAPISchemaView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    renderer_classes = [OpenAPIJSONRenderer, JSONRenderer, OpenAPIYAMLRenderer]

    def get(self, request: Request) -> Response:
        return Response(_load_openapi_contract(), status=status.HTTP_200_OK)


class OpenAPIDocsView(SpectacularSwaggerView):
    permission_classes = [AllowAny]
    authentication_classes = []
    url_name = "openapi-schema"


class SessionView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request: Request) -> Response:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise AuthenticationDomainError()

        company = DjangoCompanyScopeRepository().get_company_for_user(user.id)
        company_payload = None
        if company is not None:
            company_payload = {
                "name": company.name,
                "segment": company.segment,
                "taxRegime": company.tax_regime,
                "initialBalance": company.initial_balance.to_string(),
            }
        return Response(
            {
                "user": {"name": user.name, "email": user.email},
                "company": company_payload,
            },
            status=status.HTTP_200_OK,
        )


class ImportCollectionView(APIView):
    permission_classes = [HasCompanyScope]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request: Request) -> Response:
        jobs = ImportJobRecord.objects.for_company(request.company.id)
        return Response(ImportJobSerializer(jobs, many=True).data, status=status.HTTP_200_OK)

    def post(self, request: Request) -> Response:
        serializer = ImportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded = serializer.validated_data["file"]
        raw_bytes = uploaded.read()
        if not raw_bytes or len(raw_bytes) > 5 * 1024 * 1024:
            raise PayloadTooLargeError()

        import_type = serializer.validated_data["type"]
        sha256 = hashlib.sha256(raw_bytes).hexdigest()

        def create_job() -> tuple[int, dict]:
            job_id = uuid.uuid4()
            relative_path = tenant_storage_path(job_id, uploaded.name)
            storage_key = TenantLocalFileStorage().save_bytes(
                request.company.id,
                relative_path,
                raw_bytes,
            )
            stored_file = StoredImportFile.objects.create(
                company_id=request.company.id,
                original_filename=uploaded.name,
                storage_key=storage_key,
                size_bytes=len(raw_bytes),
                sha256=sha256,
            )
            job = ImportJobRecord.objects.create(
                id=job_id,
                company_id=request.company.id,
                stored_file=stored_file,
                created_by=request.user,
                import_type=import_type,
                filename=uploaded.name,
                status=ImportStatus.QUEUED.value,
            )
            ScopedCeleryDispatcher().enqueue_company_job(
                "imports.verify_company_job_scope",
                request.company.id,
                job.id,
            )
            job.refresh_from_db()
            return status.HTTP_202_ACCEPTED, ImportJobSerializer(job).data

        return run_idempotent(
            company=request.company,
            scope_path="/imports",
            idempotency_key=request.headers.get("Idempotency-Key"),
            payload_signature={"type": import_type, "filename": uploaded.name, "sha256": sha256},
            execute=create_job,
        )


class ImportDetailView(APIView):
    permission_classes = [HasCompanyScope]

    def get(self, request: Request, job_id: uuid.UUID) -> Response:
        job = ImportJobRecord.objects.for_company(request.company.id).filter(id=job_id).first()
        if job is None:
            raise ResourceNotFoundError("Importação não encontrada.")
        return Response(ImportJobSerializer(job).data, status=status.HTTP_200_OK)


class ImportCancelView(APIView):
    permission_classes = [HasCompanyScope]

    def post(self, request: Request, job_id: uuid.UUID) -> Response:
        job = ImportJobRecord.objects.for_company(request.company.id).filter(id=job_id).first()
        if job is None:
            raise ResourceNotFoundError("Importação não encontrada.")
        if job.status not in {
            ImportStatus.QUEUED.value,
            ImportStatus.PROCESSING.value,
            ImportStatus.REVIEW.value,
        }:
            raise StateConflictError("A importação já mudou de estado.")
        job.status = ImportStatus.CANCELED.value
        job.save(update_fields=["status", "updated_at"])
        return Response(ImportJobSerializer(job).data, status=status.HTTP_200_OK)
