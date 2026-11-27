from __future__ import annotations

from django.urls import path

from .views import (
    HealthView,
    ImportCancelView,
    ImportCollectionView,
    ImportDetailView,
    OpenAPIDocsView,
    OpenAPISchemaView,
    SessionView,
)

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("schema", OpenAPISchemaView.as_view(), name="openapi-schema"),
    path("docs", OpenAPIDocsView.as_view(url_name="openapi-schema"), name="openapi-docs"),
    path("session", SessionView.as_view(), name="session"),
    path("imports", ImportCollectionView.as_view(), name="imports-list-create"),
    path("imports/<uuid:job_id>", ImportDetailView.as_view(), name="imports-detail"),
    path("imports/<uuid:job_id>/cancel", ImportCancelView.as_view(), name="imports-cancel"),
]
