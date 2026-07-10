from rest_framework.routers import DefaultRouter

from .views import NovedadViewSet, TipoNovedadViewSet

router = DefaultRouter()
router.register("novedades", NovedadViewSet, basename="novedades")
router.register("tipos-novedad", TipoNovedadViewSet, basename="tipos-novedad")

urlpatterns = router.urls
