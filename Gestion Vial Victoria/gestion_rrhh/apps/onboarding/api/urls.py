from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ChecklistEmpleadoView,
    PlantillaChecklistViewSet,
    TildarItemChecklistView,
)

router = DefaultRouter()
router.register(
    "onboarding/plantillas", PlantillaChecklistViewSet, basename="plantillas-checklist"
)

urlpatterns = [
    # Tarjeta de la ficha: anidada bajo el empleado (la vista vive en esta app, ver views.py).
    path(
        "empleados/<int:empleado_id>/checklist/",
        ChecklistEmpleadoView.as_view(),
        name="empleado-checklist",
    ),
    path(
        "empleados/<int:empleado_id>/checklist/items/<int:item_id>/tildar/",
        TildarItemChecklistView.as_view(),
        name="empleado-checklist-tildar",
    ),
] + router.urls
