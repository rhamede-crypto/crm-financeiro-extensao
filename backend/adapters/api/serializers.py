from __future__ import annotations

from rest_framework import serializers

from adapters.persistence.models import ImportJobRecord
from core.domain.value_objects import ImportType


class ImportJobSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="import_type", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    rowCount = serializers.IntegerField(source="row_count", read_only=True, allow_null=True)
    error = serializers.SerializerMethodField()

    class Meta:
        model = ImportJobRecord
        fields = ["id", "type", "filename", "status", "createdAt", "rowCount", "error"]

    def get_error(self, obj: ImportJobRecord) -> str | None:
        return obj.error_message or None


class ImportCreateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=[item.value for item in ImportType])
    file = serializers.FileField()
