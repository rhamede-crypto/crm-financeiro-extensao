from __future__ import annotations

from django.urls import path

from .views import (
    ChatView,
    CompanyOnboardingView,
    DashboardView,
    HealthView,
    ImportCancelView,
    ImportCollectionView,
    ImportConfirmView,
    ImportDetailView,
    ImportOptionsView,
    LoginView,
    LogoutView,
    OpenAPIDocsView,
    OpenAPISchemaView,
    RegisterView,
    SessionView,
)

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("schema", OpenAPISchemaView.as_view(), name="openapi-schema"),
    path("docs", OpenAPIDocsView.as_view(url_name="openapi-schema"), name="openapi-docs"),
    path("session", SessionView.as_view(), name="session"),
    path("auth/register", RegisterView.as_view(), name="auth-register"),
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("company", CompanyOnboardingView.as_view(), name="company-onboarding"),
    path("imports/options", ImportOptionsView.as_view(), name="imports-options"),
    path("imports", ImportCollectionView.as_view(), name="imports-list-create"),
    path("imports/<uuid:job_id>", ImportDetailView.as_view(), name="imports-detail"),
    path("imports/<uuid:job_id>/confirm", ImportConfirmView.as_view(), name="imports-confirm"),
    path("imports/<uuid:job_id>/cancel", ImportCancelView.as_view(), name="imports-cancel"),
    path("dashboard", DashboardView.as_view(), name="dashboard"),
    path("chat", ChatView.as_view(), name="chat"),
]
