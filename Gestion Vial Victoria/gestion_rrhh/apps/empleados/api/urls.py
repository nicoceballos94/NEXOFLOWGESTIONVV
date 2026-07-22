from rest_framework.routers import DefaultRouter

from .views import EmpleadoViewSet, TipoDocumentoViewSet

router = DefaultRouter()
router.register("empleados", EmpleadoViewSet, basename="empleados")
router.register("tipos-documento", TipoDocumentoViewSet, basename="tipos-documento")

urlpatterns = router.urls
