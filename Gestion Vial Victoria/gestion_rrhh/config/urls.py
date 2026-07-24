"""Ruteo raíz. Toda la API vive bajo /api/v1/ (convención §8 del diseño)."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from config.views import healthcheck

urlpatterns = [
    path("healthz/", healthcheck, name="healthcheck"),
    path("admin/", admin.site.urls),
    # Apps de dominio
    path("api/v1/", include("apps.usuarios.api.urls")),
    path("api/v1/", include("apps.organizacion.api.urls")),
    path("api/v1/", include("apps.empleados.api.urls")),
    path("api/v1/", include("apps.novedades.api.urls")),
    path("api/v1/", include("apps.dashboard.api.urls")),
    path("api/v1/", include("apps.onboarding.api.urls")),
    path("api/v1/", include("apps.auditoria.api.urls")),
]

# El contrato se genera/valida en CI. La UI interactiva existe solo en desarrollo para no
# publicar gratis toda la superficie de la API en producción.
if settings.DEBUG:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
    ]
