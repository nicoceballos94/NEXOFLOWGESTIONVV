from rest_framework.routers import DefaultRouter

from .views import RegistroAuditoriaViewSet

router = DefaultRouter()
router.register("auditoria/registros", RegistroAuditoriaViewSet, basename="auditoria-registros")

urlpatterns = router.urls
