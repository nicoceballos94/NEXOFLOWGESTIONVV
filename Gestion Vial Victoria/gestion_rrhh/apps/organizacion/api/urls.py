from rest_framework.routers import DefaultRouter

from .views import EmpresaViewSet, PuestoViewSet, SectorViewSet

router = DefaultRouter()
router.register("empresas", EmpresaViewSet, basename="empresas")
router.register("sectores", SectorViewSet, basename="sectores")
router.register("puestos", PuestoViewSet, basename="puestos")

urlpatterns = router.urls
