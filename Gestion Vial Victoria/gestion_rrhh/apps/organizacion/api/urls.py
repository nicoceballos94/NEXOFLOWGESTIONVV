from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ConfigVencimientosView, EmpresaViewSet, PuestoViewSet, SectorViewSet

router = DefaultRouter()
router.register("empresas", EmpresaViewSet, basename="empresas")
router.register("sectores", SectorViewSet, basename="sectores")
router.register("puestos", PuestoViewSet, basename="puestos")

urlpatterns = [
    path(
        "config/vencimientos/",
        ConfigVencimientosView.as_view(),
        name="config-vencimientos",
    ),
] + router.urls
