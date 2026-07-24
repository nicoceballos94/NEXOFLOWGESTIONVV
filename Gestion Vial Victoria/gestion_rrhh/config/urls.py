"""Ruteo raíz. Toda la API vive bajo /api/v1/ (convención §8 del diseño)."""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.usuarios.api.views import LoginThrottledView, RefreshThrottledView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Autenticación JWT
    path("api/v1/auth/token/", LoginThrottledView.as_view(), name="token_obtain_pair"),
    path("api/v1/auth/token/refresh/", RefreshThrottledView.as_view(), name="token_refresh"),
    # Apps de dominio
    path("api/v1/", include("apps.usuarios.api.urls")),
    path("api/v1/", include("apps.organizacion.api.urls")),
    path("api/v1/", include("apps.empleados.api.urls")),
    path("api/v1/", include("apps.novedades.api.urls")),
    path("api/v1/", include("apps.dashboard.api.urls")),
    path("api/v1/", include("apps.onboarding.api.urls")),
    path("api/v1/", include("apps.auditoria.api.urls")),
    # Contrato OpenAPI — fuente de verdad para el frontend (Claude Design) y n8n
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
