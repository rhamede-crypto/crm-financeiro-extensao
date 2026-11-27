from __future__ import annotations

from rest_framework import serializers

from adapters.persistence.models import ImportJobRecord
from core.domain.value_objects import Weekday


class RegisterSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(min_length=8, max_length=128, write_only=True)

    def validate_name(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Informe seu nome.")
        return cleaned

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=128, write_only=True)

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class CompanyOnboardingSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=140, trim_whitespace=True)
    segment = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    taxRegime = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    tax_regime = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    initialBalance = serializers.CharField(required=False, allow_blank=True, default="")
    initial_balance = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_name(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Informe o nome da empresa.")
        return cleaned


class ImportJobSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="import_type", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    rowCount = serializers.IntegerField(source="row_count", read_only=True, allow_null=True)
    uploadDurationMs = serializers.IntegerField(
        source="upload_duration_ms",
        read_only=True,
        allow_null=True,
    )
    processingDurationMs = serializers.IntegerField(
        source="processing_duration_ms",
        read_only=True,
        allow_null=True,
    )
    columns = serializers.JSONField(source="columns_json", read_only=True)
    fields = serializers.JSONField(source="fields_json", read_only=True)
    mapping = serializers.JSONField(source="mapping_json", read_only=True)
    selectedMapping = serializers.JSONField(source="selected_mapping_json", read_only=True)
    preview = serializers.JSONField(source="preview_json", read_only=True)
    ambiguities = serializers.JSONField(source="ambiguities_json", read_only=True)
    summary = serializers.JSONField(source="summary_json", read_only=True)
    error = serializers.SerializerMethodField()

    class Meta:
        model = ImportJobRecord
        fields = [
            "id",
            "type",
            "filename",
            "status",
            "createdAt",
            "rowCount",
            "uploadDurationMs",
            "processingDurationMs",
            "columns",
            "fields",
            "mapping",
            "selectedMapping",
            "preview",
            "ambiguities",
            "summary",
            "error",
        ]

    def get_error(self, obj: ImportJobRecord) -> str | None:
        return obj.error_message or None


class ImportCreateSerializer(serializers.Serializer):
    type = serializers.CharField(max_length=32)
    file = serializers.FileField()


class ImportConfirmSerializer(serializers.Serializer):
    mapping = serializers.DictField(child=serializers.CharField(allow_blank=True))
    resolutions = serializers.DictField(
        child=serializers.ChoiceField(choices=["new", "ignore"]),
        required=False,
        default=dict,
    )


class ChatRequestSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000, trim_whitespace=True)

    def validate_question(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Escreva uma pergunta.")
        return cleaned


class ReminderPreferencesSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    weekday = serializers.ChoiceField(choices=[item.value for item in Weekday])


class CollectionPreviewSerializer(serializers.Serializer):
    tone = serializers.ChoiceField(
        choices=["friendly", "firm", "negotiation"],
        required=False,
        default="friendly",
    )


class CollectionSendSerializer(serializers.Serializer):
    tone = serializers.ChoiceField(
        choices=["friendly", "firm", "negotiation"],
        required=False,
        default="friendly",
    )
    text = serializers.CharField(max_length=4000, trim_whitespace=True)
    channel = serializers.CharField(max_length=64, required=False, default="email")

    def validate_text(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Revise a mensagem antes de enviar.")
        return cleaned
