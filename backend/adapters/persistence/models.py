from __future__ import annotations

import uuid
from decimal import Decimal

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from core.domain.exceptions import TenantAccessDeniedError
from core.domain.value_objects import DealStage, ImportStatus, ImportType, Weekday


class UserManager(BaseUserManager["User"]):
    def create_user(
        self,
        email: str,
        name: str,
        password: str | None = None,
        **extra_fields: object,
    ) -> User:
        normalized_email = self.normalize_email(email).strip().lower()
        if not normalized_email:
            raise ValueError("E-mail obrigatório.")
        user = self.model(email=normalized_email, name=name.strip(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        name: str,
        password: str | None = None,
        **extra_fields: object,
    ) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email=email, name=name, password=password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(max_length=254, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        return self.email


class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=140)
    segment = models.CharField(max_length=120, blank=True, default="")
    tax_regime = models.CharField(max_length=64, blank=True, default="")
    initial_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    last_consolidated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "companies"

    def __str__(self) -> str:
        return self.name


class CompanyMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="membership",
    )
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=32, default="owner")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "company_memberships"


class TenantQuerySet(models.QuerySet):
    def for_company(self, company_id: uuid.UUID | None) -> TenantQuerySet:
        if company_id is None:
            raise TenantAccessDeniedError("Escopo de empresa obrigatório na consulta.")
        return self.filter(company_id=company_id)


class TenantScopedManager(models.Manager):
    def get_queryset(self) -> TenantQuerySet:
        return TenantQuerySet(self.model, using=self._db)

    def for_company(self, company_id: uuid.UUID | None) -> TenantQuerySet:
        return self.get_queryset().for_company(company_id)


class TenantScopedModel(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    objects = TenantScopedManager()
    unscoped = models.Manager()

    class Meta:
        abstract = True


class StoredImportFile(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_filename = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=512)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stored_import_files"
        indexes = [
            models.Index(fields=["company", "created_at"]),
        ]


class ImportJobRecord(TenantScopedModel):
    STATUS_CHOICES = [(item.value, item.value) for item in ImportStatus]
    TYPE_CHOICES = [(item.value, item.value) for item in ImportType]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stored_file = models.ForeignKey(
        StoredImportFile,
        on_delete=models.PROTECT,
        related_name="import_jobs",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="import_jobs",
    )
    import_type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    filename = models.CharField(max_length=255)
    status = models.CharField(
        max_length=24,
        choices=STATUS_CHOICES,
        default=ImportStatus.QUEUED.value,
    )
    error_message = models.TextField(blank=True, default="")
    row_count = models.PositiveIntegerField(null=True, blank=True)
    upload_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    processing_duration_ms = models.PositiveIntegerField(null=True, blank=True)
    columns_json = models.JSONField(default=list, blank=True)
    fields_json = models.JSONField(default=list, blank=True)
    mapping_json = models.JSONField(default=dict, blank=True)
    selected_mapping_json = models.JSONField(default=dict, blank=True)
    preview_json = models.JSONField(default=list, blank=True)
    ambiguities_json = models.JSONField(default=list, blank=True)
    summary_json = models.JSONField(null=True, blank=True)
    parsed_rows_storage_key = models.CharField(max_length=512, blank=True, default="")
    last_worker_task_id = models.CharField(max_length=128, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "import_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "created_at"]),
            models.Index(fields=["company", "status"]),
        ]


class Contact(TenantScopedModel):
    TYPE_CHOICES = [("customer", "customer"), ("supplier", "supplier")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    normalized_name = models.CharField(max_length=160)
    contact_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    document = models.CharField(max_length=32, blank=True, default="")
    normalized_document = models.CharField(max_length=32, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    normalized_phone = models.CharField(max_length=32, blank=True, default="")
    email = models.EmailField(max_length=254, blank=True, default="")
    needs_review = models.BooleanField(default=False)
    review_reason = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "contacts"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["company", "contact_type", "normalized_document"]),
            models.Index(fields=["company", "contact_type", "normalized_phone"]),
            models.Index(fields=["company", "contact_type", "normalized_name"]),
        ]


class FinancialEntry(TenantScopedModel):
    TYPE_CHOICES = [(item.value, item.value) for item in ImportType]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    import_job = models.ForeignKey(
        ImportJobRecord,
        on_delete=models.PROTECT,
        related_name="entries",
    )
    contact = models.ForeignKey(
        Contact,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entries",
    )
    entry_type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    reference = models.CharField(max_length=120, blank=True, default="")
    entry_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    description = models.CharField(max_length=255)
    normalized_description = models.CharField(max_length=255)
    party_name = models.CharField(max_length=160, blank=True, default="")
    normalized_party = models.CharField(max_length=160, blank=True, default="")
    category = models.CharField(max_length=80, blank=True, default="")
    unit_name = models.CharField(max_length=40, blank=True, default="")
    unit_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    settled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "financial_entries"
        indexes = [
            models.Index(fields=["company", "entry_type", "reference"]),
            models.Index(fields=["company", "entry_type", "settled", "due_date"]),
            models.Index(fields=["company", "entry_date"]),
        ]


class ReminderPreference(models.Model):
    WEEKDAY_CHOICES = [(item.value, item.value) for item in Weekday]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="reminder_preference",
    )
    enabled = models.BooleanField(default=False)
    weekday = models.CharField(
        max_length=16,
        choices=WEEKDAY_CHOICES,
        default=Weekday.MONDAY.value,
    )
    channel = models.CharField(max_length=32, default="email")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reminder_preferences"


class ReminderDispatchLog(TenantScopedModel):
    STATUS_CHOICES = [
        ("sent", "sent"),
        ("failed", "failed"),
        ("skipped_up_to_date", "skipped_up_to_date"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    iso_year = models.PositiveSmallIntegerField()
    iso_week = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=24, choices=STATUS_CHOICES)
    detail = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reminder_dispatch_logs"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "iso_year", "iso_week"],
                name="uniq_company_weekly_reminder",
            ),
        ]


class CollectionDispatch(TenantScopedModel):
    STATUS_CHOICES = [("sent", "sent"), ("failed", "failed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="collection_dispatches",
    )
    tone = models.CharField(max_length=24)
    channel = models.CharField(max_length=32, default="email")
    recipient = models.CharField(max_length=254)
    message_text = models.TextField()
    status = models.CharField(max_length=24, choices=STATUS_CHOICES)
    reason = models.CharField(max_length=200, blank=True, default="")
    sent_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="collection_dispatches",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "collection_dispatches"
        ordering = ["-created_at"]


class Deal(TenantScopedModel):
    STAGE_CHOICES = [(item.value, item.value) for item in DealStage]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="deals",
    )
    financial_entry = models.ForeignKey(
        FinancialEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deals",
    )
    title = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    due_date = models.DateField(null=True, blank=True)
    stage = models.CharField(
        max_length=24,
        choices=STAGE_CHOICES,
        default=DealStage.IDENTIFIED.value,
    )
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "deals"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["company", "stage"]),
        ]


class DealTransitionLog(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deal = models.ForeignKey(
        Deal,
        on_delete=models.CASCADE,
        related_name="transitions",
    )
    author = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deal_transitions",
    )
    previous_stage = models.CharField(max_length=24)
    new_stage = models.CharField(max_length=24)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "deal_transition_logs"
        ordering = ["-created_at"]


class SupplierAgreement(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="agreements",
    )
    agreement_date = models.DateField()
    terms = models.TextField()
    alert_id = models.CharField(max_length=120, blank=True, default="")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplier_agreements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "supplier_agreements"
        ordering = ["-created_at"]


class IdempotencyRecord(TenantScopedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope_path = models.CharField(max_length=200)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    response_body = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "idempotency_records"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "scope_path", "idempotency_key"],
                name="uniq_company_scope_idempotency",
            ),
        ]
