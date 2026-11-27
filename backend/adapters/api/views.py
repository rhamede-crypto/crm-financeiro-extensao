from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path

import yaml
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularSwaggerView
from rest_framework import renderers, serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from adapters.notifications.email_adapter import DjangoEmailNotificationAdapter
from adapters.persistence.consolidation import consolidate_import_job
from adapters.persistence.dashboard_service import build_company_dashboard
from adapters.persistence.models import (
    CollectionDispatch,
    Company,
    CompanyMembership,
    Contact,
    Deal,
    DealTransitionLog,
    FinancialEntry,
    ImportJobRecord,
    ReminderPreference,
    StoredImportFile,
    SupplierAgreement,
    User,
)
from adapters.persistence.probes import DatabaseHealthProbe
from adapters.persistence.repositories import DjangoCompanyScopeRepository
from adapters.queue.celery_dispatcher import ScopedCeleryDispatcher
from adapters.queue.probes import RedisBrokerHealthProbe
from adapters.storage.local_storage import TenantLocalFileStorage
from adapters.storage.spreadsheet_reader import (
    MAX_DATA_ROWS,
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    normalize_import_type,
    read_spreadsheet_table,
)
from core.domain.exceptions import (
    AuthenticationDomainError,
    PayloadTooLargeError,
    ResourceNotFoundError,
    StateConflictError,
    ValidationDomainError,
)
from core.domain.value_objects import (
    CivilDate,
    CompanySegment,
    DealStage,
    ImportStatus,
    MoneyDecimal,
    TaxRegime,
    normalize_ascii_text,
    validate_deal_transition,
)
from core.ports.notifications import NotificationMessage
from core.services.advisor import answer_financial_question
from core.services.collections import build_collection_message
from core.services.customer_metrics import CustomerEntryInput, compute_customer_profile
from core.services.health import HealthService
from core.services.supplier_costs import SupplierCostEntry, build_supplier_cost_history

from .idempotency import run_idempotent, tenant_storage_path
from .permissions import HasCompanyScope
from .serializers import (
    ChatRequestSerializer,
    CollectionPreviewSerializer,
    CollectionSendSerializer,
    CompanyOnboardingSerializer,
    DealMoveSerializer,
    ImportConfirmSerializer,
    ImportCreateSerializer,
    ImportJobSerializer,
    LoginSerializer,
    RegisterSerializer,
    ReminderPreferencesSerializer,
    SupplierAgreementSerializer,
)

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


def _session_payload(user: User) -> dict:
    company = DjangoCompanyScopeRepository().get_company_for_user(user.id)
    company_payload = None
    if company is not None:
        company_payload = {
            "name": company.name,
            "segment": company.segment,
            "taxRegime": company.tax_regime,
            "initialBalance": company.initial_balance.to_string(),
        }
    return {
        "user": {"name": user.name, "email": user.email},
        "company": company_payload,
    }


class SessionView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request: Request) -> Response:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise AuthenticationDomainError()
        return Response(_session_payload(user), status=status.HTTP_200_OK)


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if User.objects.filter(email=data["email"]).exists():
            raise ValidationDomainError(
                "Confira os dados do cadastro.",
                fields={"email": ["E-mail já cadastrado."]},
            )
        try:
            user = User.objects.create_user(
                email=data["email"],
                name=data["name"],
                password=data["password"],
            )
        except IntegrityError as exc:
            raise ValidationDomainError(
                "Confira os dados do cadastro.",
                fields={"email": ["E-mail já cadastrado."]},
            ) from exc

        login(request, user)
        return Response(_session_payload(user), status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = authenticate(request, username=data["email"], password=data["password"])
        if user is None or not user.is_active:
            raise AuthenticationDomainError(
                "E-mail ou senha inválidos.",
                code="invalid_credentials",
            )
        login(request, user)
        return Response(_session_payload(user), status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompanyOnboardingView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        if CompanyMembership.objects.filter(user=request.user).exists():
            raise StateConflictError("A empresa já está cadastrada.")

        serializer = CompanyOnboardingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        segment = CompanySegment.parse(
            data.get("segment"),
            default=CompanySegment.COMERCIO_LOCAL,
        )
        raw_regime = data.get("taxRegime") or data.get("tax_regime") or ""
        tax_regime = TaxRegime.parse(raw_regime, default=TaxRegime.SIMPLES_NACIONAL)

        raw_balance = request.data.get("initialBalance", request.data.get("initial_balance"))
        if raw_balance in (None, ""):
            initial_balance = MoneyDecimal.from_value("0.00")
        elif isinstance(raw_balance, float):
            raise ValidationDomainError(
                "Saldo inicial inválido.",
                fields={"initialBalance": ["Envie o saldo em texto decimal, como '1500.00'."]},
            )
        else:
            try:
                initial_balance = MoneyDecimal.from_value(str(raw_balance))
            except ValidationDomainError as exc:
                raise ValidationDomainError(
                    "Saldo inicial inválido.",
                    fields={"initialBalance": exc.fields.get("amount", ["Formato inválido."])},
                ) from exc

        with transaction.atomic():
            if CompanyMembership.objects.filter(user=request.user).exists():
                raise StateConflictError("A empresa já está cadastrada.")
            company = Company.objects.create(
                name=data["name"],
                segment=segment.value,
                tax_regime=tax_regime.value,
                initial_balance=initial_balance.amount,
            )
            CompanyMembership.objects.create(
                user=request.user,
                company=company,
                role="owner",
            )

        return Response(_session_payload(request.user), status=status.HTTP_201_CREATED)


class ImportOptionsView(APIView):
    permission_classes = [HasCompanyScope]

    def get(self, request: Request) -> Response:
        return Response(
            {
                "maxBytes": MAX_UPLOAD_BYTES,
                "maxRows": MAX_DATA_ROWS,
                "extensions": list(SUPPORTED_EXTENSIONS),
                "types": [
                    {"id": "receivable", "label": "Contas a receber"},
                    {"id": "payable", "label": "Contas a pagar"},
                    {"id": "settled", "label": "Lançamentos efetivados"},
                ],
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
        upload_started = time.perf_counter()
        serializer = ImportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded = serializer.validated_data["file"]
        raw_bytes = uploaded.read()
        if not raw_bytes or len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise PayloadTooLargeError()

        import_type = normalize_import_type(serializer.validated_data["type"])
        read_spreadsheet_table(uploaded.name, raw_bytes)
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
            upload_duration_ms = max(1, int((time.perf_counter() - upload_started) * 1000))
            job = ImportJobRecord.objects.create(
                id=job_id,
                company_id=request.company.id,
                stored_file=stored_file,
                created_by=request.user,
                import_type=import_type,
                filename=uploaded.name,
                status=ImportStatus.QUEUED.value,
                upload_duration_ms=upload_duration_ms,
            )
            ScopedCeleryDispatcher().enqueue_company_job(
                "imports.process_import_job",
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


class ImportConfirmView(APIView):
    permission_classes = [HasCompanyScope]

    def post(self, request: Request, job_id: uuid.UUID) -> Response:
        serializer = ImportConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mapping = serializer.validated_data["mapping"]
        resolutions = serializer.validated_data.get("resolutions", {})

        def confirm() -> tuple[int, dict]:
            job = ImportJobRecord.objects.for_company(request.company.id).filter(id=job_id).first()
            if job is None:
                raise ResourceNotFoundError("Importação não encontrada.")
            if job.status != ImportStatus.REVIEW.value:
                raise StateConflictError("A importação já mudou de estado.")
            updated = consolidate_import_job(
                company=request.company,
                job=job,
                mapping=mapping,
                resolutions=resolutions,
            )
            return status.HTTP_200_OK, ImportJobSerializer(updated).data

        return run_idempotent(
            company=request.company,
            scope_path=f"/imports/{job_id}/confirm",
            idempotency_key=request.headers.get("Idempotency-Key"),
            payload_signature={"mapping": mapping, "resolutions": resolutions},
            execute=confirm,
        )


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


class DashboardView(APIView):
    permission_classes = [HasCompanyScope]

    def get(self, request: Request) -> Response:
        return Response(build_company_dashboard(request.company), status=status.HTTP_200_OK)


class ChatView(APIView):
    permission_classes = [HasCompanyScope]

    def post(self, request: Request) -> Response:
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question = serializer.validated_data["question"]

        def reply() -> tuple[int, dict]:
            dashboard = build_company_dashboard(request.company)
            answer = answer_financial_question(
                question=question,
                dashboard=dashboard,
                company_name=request.company.name,
            )
            return status.HTTP_200_OK, answer

        return run_idempotent(
            company=request.company,
            scope_path="/chat",
            idempotency_key=request.headers.get("Idempotency-Key"),
            payload_signature={"question": question},
            execute=reply,
        )


def _reminder_payload(company: Company, pref: ReminderPreference) -> dict:
    available = bool(getattr(settings, "EMAIL_HOST", "").strip())
    return {
        "available": available,
        "channel": "E-mail",
        "enabled": pref.enabled,
        "weekday": pref.weekday,
        "lastConsolidated": company.last_consolidated_at.isoformat()
        if company.last_consolidated_at
        else None,
    }


class RemindersView(APIView):
    permission_classes = [HasCompanyScope]

    def get(self, request: Request) -> Response:
        pref, _ = ReminderPreference.objects.get_or_create(company=request.company)
        return Response(_reminder_payload(request.company, pref), status=status.HTTP_200_OK)

    def put(self, request: Request) -> Response:
        if not getattr(settings, "EMAIL_HOST", "").strip():
            raise StateConflictError("O canal está indisponível.")
        serializer = ReminderPreferencesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pref, _ = ReminderPreference.objects.get_or_create(company=request.company)
        pref.enabled = serializer.validated_data["enabled"]
        pref.weekday = serializer.validated_data["weekday"]
        pref.save(update_fields=["enabled", "weekday", "updated_at"])
        return Response(_reminder_payload(request.company, pref), status=status.HTTP_200_OK)


class ContactsCollectionView(APIView):
    permission_classes = [HasCompanyScope]

    def get(self, request: Request) -> Response:
        query = normalize_ascii_text(request.query_params.get("query", ""))
        ctype = request.query_params.get("type", "").strip()
        qs = Contact.objects.for_company(request.company.id)
        if ctype in {"customer", "supplier"}:
            qs = qs.filter(contact_type=ctype)
        if query:
            qs = qs.filter(normalized_name__icontains=query)

        payload = [
            {
                "id": str(contact.id),
                "name": contact.name,
                "type": contact.contact_type,
                "needsReview": contact.needs_review,
            }
            for contact in qs
        ]
        return Response(payload, status=status.HTTP_200_OK)


class ContactDetailView(APIView):
    permission_classes = [HasCompanyScope]

    def get(self, request: Request, contact_id: uuid.UUID) -> Response:
        contact = Contact.objects.for_company(request.company.id).filter(id=contact_id).first()
        if contact is None:
            raise ResourceNotFoundError("Ficha indisponível.")

        payload = {
            "id": str(contact.id),
            "name": contact.name,
            "type": contact.contact_type,
            "document": contact.document,
            "phone": contact.phone,
            "email": contact.email,
            "needsReview": contact.needs_review,
            "reviewReason": contact.review_reason or None,
            "invoices": [],
            "history": [],
            "costHistory": [],
            "alerts": [],
            "agreements": [],
        }

        if contact.contact_type == "customer":
            db_entries = FinancialEntry.objects.for_company(request.company.id).filter(
                contact=contact
            )
            profile = compute_customer_profile(
                entries=[
                    CustomerEntryInput(
                        entry_id=e.reference or str(e.id),
                        entry_date=e.entry_date,
                        due_date=e.due_date,
                        amount=e.amount,
                        paid_amount=e.paid_amount,
                        description=e.description,
                        settled=e.settled,
                    )
                    for e in db_entries
                ],
                reference_date=timezone.localdate(),
            )
            payload.update(profile)
        elif contact.contact_type == "supplier":
            db_entries = FinancialEntry.objects.for_company(request.company.id).filter(
                contact=contact
            )
            cost_data = build_supplier_cost_history(
                [
                    SupplierCostEntry(
                        entry_date=e.entry_date,
                        amount=e.amount,
                        unit_name=e.unit_name,
                        unit_price=e.unit_price,
                    )
                    for e in db_entries
                ]
            )
            dashboard = build_company_dashboard(request.company)
            supplier_alerts = [
                alert
                for alert in dashboard.get("alerts", [])
                if alert.get("supplierId") == str(contact.id)
                or normalize_ascii_text(alert.get("supplier")) == contact.normalized_name
            ]
            agreements = [
                {
                    "id": str(ag.id),
                    "date": ag.agreement_date.isoformat(),
                    "terms": ag.terms,
                    "alertId": ag.alert_id or None,
                }
                for ag in SupplierAgreement.objects.for_company(request.company.id).filter(
                    contact=contact
                )
            ]
            payload.update(cost_data)
            payload["alerts"] = supplier_alerts
            payload["agreements"] = agreements

        return Response(payload, status=status.HTTP_200_OK)


class SupplierAgreementCreateView(APIView):
    permission_classes = [HasCompanyScope]

    def post(self, request: Request, contact_id: uuid.UUID) -> Response:
        contact = Contact.objects.for_company(request.company.id).filter(id=contact_id).first()
        if contact is None:
            raise ResourceNotFoundError("Ficha indisponível.")
        if contact.contact_type != "supplier":
            raise ValidationDomainError(
                "Esta ficha não é de um fornecedor.",
                fields={"contact": ["Acordos são permitidos apenas para fornecedores."]},
            )

        serializer = SupplierAgreementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        agreement_date = CivilDate.from_iso(serializer.validated_data["date"]).value
        alert_id = (serializer.validated_data.get("alertId") or "").strip()

        agreement = SupplierAgreement.objects.create(
            company_id=request.company.id,
            contact=contact,
            agreement_date=agreement_date,
            terms=serializer.validated_data["terms"],
            alert_id=alert_id,
            created_by=request.user,
        )
        return Response(
            {
                "id": str(agreement.id),
                "date": agreement.agreement_date.isoformat(),
                "terms": agreement.terms,
                "alertId": agreement.alert_id or None,
            },
            status=status.HTTP_201_CREATED,
        )


def _open_customer_invoices(company: Company, contact: Contact) -> list[dict]:
    from django.utils import timezone

    db_entries = FinancialEntry.objects.for_company(company.id).filter(contact=contact)
    profile = compute_customer_profile(
        entries=[
            CustomerEntryInput(
                entry_id=e.reference or str(e.id),
                entry_date=e.entry_date,
                due_date=e.due_date,
                amount=e.amount,
                paid_amount=e.paid_amount,
                description=e.description,
                settled=e.settled,
            )
            for e in db_entries
        ],
        reference_date=timezone.localdate(),
    )
    return profile["invoices"]


class CollectionPreviewView(APIView):
    permission_classes = [HasCompanyScope]

    def post(self, request: Request, contact_id: uuid.UUID) -> Response:
        contact = Contact.objects.for_company(request.company.id).filter(id=contact_id).first()
        if contact is None:
            raise ResourceNotFoundError("Ficha indisponível.")

        serializer = CollectionPreviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tone = serializer.validated_data["tone"]

        if not getattr(settings, "EMAIL_HOST", "").strip():
            return Response(
                {"available": False, "reason": "Canal de e-mail indisponível no momento."},
                status=status.HTTP_200_OK,
            )
        if not contact.email.strip():
            return Response(
                {
                    "available": False,
                    "reason": "O cliente não possui e-mail cadastrado para cobrança.",
                },
                status=status.HTTP_200_OK,
            )

        invoices = _open_customer_invoices(request.company, contact)
        if not invoices:
            return Response(
                {"available": False, "reason": "O cliente não possui faturas em aberto."},
                status=status.HTTP_200_OK,
            )

        text = build_collection_message(
            tone=tone,
            contact_name=contact.name,
            company_name=request.company.name,
            invoices=invoices,
        )
        return Response(
            {
                "available": True,
                "channel": "E-mail",
                "channelId": "email",
                "recipient": contact.email,
                "text": text,
            },
            status=status.HTTP_200_OK,
        )


class CollectionSendView(APIView):
    permission_classes = [HasCompanyScope]

    def post(self, request: Request, contact_id: uuid.UUID) -> Response:
        contact = Contact.objects.for_company(request.company.id).filter(id=contact_id).first()
        if contact is None:
            raise ResourceNotFoundError("Ficha indisponível.")

        serializer = CollectionSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tone = serializer.validated_data["tone"]
        text = serializer.validated_data["text"]

        if not getattr(settings, "EMAIL_HOST", "").strip():
            raise StateConflictError("Canal de cobrança indisponível.")
        if not contact.email.strip():
            raise ValidationDomainError(
                "Destinatário ausente para o cliente.",
                fields={"recipient": ["Cadastre um e-mail para enviar cobrança."]},
            )

        def dispatch() -> tuple[int, dict]:
            receipt = DjangoEmailNotificationAdapter().send(
                NotificationMessage(
                    company_id=request.company.id,
                    recipient=contact.email,
                    subject=f"Cobrança — {request.company.name}",
                    body=text,
                    channel="email",
                )
            )
            record = CollectionDispatch.objects.create(
                company_id=request.company.id,
                contact=contact,
                tone=tone,
                channel="email",
                recipient=contact.email,
                message_text=text,
                status=receipt.status,
                reason=receipt.reason,
                sent_by=request.user,
            )
            if receipt.status == "sent":
                identified_deals = list(
                    Deal.objects.for_company(request.company.id).filter(
                        contact=contact,
                        stage=DealStage.IDENTIFIED.value,
                    )
                )
                for d in identified_deals:
                    d.stage = DealStage.CONTACTED.value
                    d.version += 1
                    d.save(update_fields=["stage", "version", "updated_at"])
                    DealTransitionLog.objects.create(
                        company_id=request.company.id,
                        deal=d,
                        author=request.user,
                        previous_stage=DealStage.IDENTIFIED.value,
                        new_stage=DealStage.CONTACTED.value,
                    )
            return status.HTTP_200_OK, {
                "id": str(record.id),
                "status": record.status,
                "channel": record.channel,
                "reason": record.reason or None,
            }

        return run_idempotent(
            company=request.company,
            scope_path=f"/contacts/{contact_id}/collections/send",
            idempotency_key=request.headers.get("Idempotency-Key"),
            payload_signature={"tone": tone, "text": text, "channel": "email"},
            execute=dispatch,
        )


def _deal_payload(deal: Deal) -> dict:
    return {
        "id": str(deal.id),
        "contactId": str(deal.contact_id),
        "title": deal.title,
        "name": deal.contact.name,
        "amount": f"{deal.amount:.2f}",
        "due": deal.due_date.isoformat() if deal.due_date else None,
        "stage": deal.stage,
        "version": deal.version,
        "transitions": [
            {
                "previousStage": log.previous_stage,
                "newStage": log.new_stage,
                "author": log.author.name if log.author else "Sistema",
                "createdAt": log.created_at.isoformat(),
            }
            for log in deal.transitions.select_related("author").all()[:10]
        ],
    }


class DealsCollectionView(APIView):
    permission_classes = [HasCompanyScope]

    def get(self, request: Request) -> Response:
        deals = (
            Deal.objects.for_company(request.company.id)
            .select_related("contact")
            .prefetch_related("transitions__author")
        )
        return Response([_deal_payload(d) for d in deals], status=status.HTTP_200_OK)


class DealDetailView(APIView):
    permission_classes = [HasCompanyScope]

    def patch(self, request: Request, deal_id: uuid.UUID) -> Response:
        serializer = DealMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_raw = serializer.validated_data["stage"]
        expected_version = serializer.validated_data["version"]

        with transaction.atomic():
            deal = (
                Deal.objects.for_company(request.company.id)
                .select_for_update()
                .select_related("contact")
                .filter(id=deal_id)
                .first()
            )
            if deal is None:
                raise ResourceNotFoundError("Negociação indisponível.")
            if deal.version != expected_version:
                raise StateConflictError("O cartão mudou. O quadro foi recarregado.")
            target_stage = validate_deal_transition(deal.stage, target_raw)
            if deal.stage == target_stage.value:
                return Response(_deal_payload(deal), status=status.HTTP_200_OK)

            previous_stage = deal.stage
            updated = (
                Deal.objects.for_company(request.company.id)
                .filter(id=deal.id, version=expected_version)
                .update(
                    stage=target_stage.value,
                    version=F("version") + 1,
                    updated_at=timezone.now(),
                )
            )
            if updated != 1:
                raise StateConflictError("O cartão mudou. O quadro foi recarregado.")

            DealTransitionLog.objects.create(
                company_id=request.company.id,
                deal=deal,
                author=request.user,
                previous_stage=previous_stage,
                new_stage=target_stage.value,
            )
            deal.refresh_from_db()
            return Response(_deal_payload(deal), status=status.HTTP_200_OK)
