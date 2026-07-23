"""Views flacas (§11): autentican, validan forma, delegan en service/selector.

Dos superficies:
- **ABM de plantillas** (`/onboarding/plantillas/`): Configuración. Escritura RRHH/Admin.
- **Tarjeta de la ficha** (`/empleados/{id}/checklist/`): anidada bajo el empleado, pero la
  vista vive acá para no invertir la dependencia (empleados NO conoce a onboarding). Lectura
  para quien puede ver la ficha; tildar, RRHH/Admin.
"""
from django.shortcuts import get_object_or_404
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.empleados import selectors as empleados_selectors
from apps.empleados.models import EstadoRelacion
from common import roles
from common.permissions import LecturaAutenticadaEscrituraPorRol, RolRequerido

from .. import selectors, services
from ..models import ItemProceso, PlantillaChecklist, ProcesoEmpleado, TipoProceso
from .serializers import (
    ActualizarItemSerializer,
    ActualizarPlantillaSerializer,
    CrearItemSerializer,
    CrearPlantillaSerializer,
    PlantillaChecklistSerializer,
    TildarItemSerializer,
)

_SoloRRHH = RolRequerido(roles.ADMIN, roles.RRHH)


class PlantillaChecklistViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """ABM de plantillas de checklist (Configuración). Lectura autenticada; escritura RRHH."""

    serializer_class = PlantillaChecklistSerializer
    permission_classes = [LecturaAutenticadaEscrituraPorRol(roles.ADMIN, roles.RRHH)]

    def get_queryset(self):
        return selectors.plantillas_visibles(filtros=self.request.query_params)

    def create(self, request):
        entrada = CrearPlantillaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        plantilla = services.crear_plantilla(actor=request.user, **entrada.validated_data)
        return Response(PlantillaChecklistSerializer(plantilla).data, status=201)

    def partial_update(self, request, pk=None):
        plantilla = get_object_or_404(PlantillaChecklist, pk=pk)
        entrada = ActualizarPlantillaSerializer(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        plantilla.activa = entrada.validated_data["activa"]
        plantilla.save(update_fields=["activa", "actualizado_en"])
        return Response(PlantillaChecklistSerializer(plantilla).data)

    @action(detail=True, methods=["post"], url_path="items")
    def crear_item(self, request, pk=None):
        plantilla = get_object_or_404(PlantillaChecklist, pk=pk)
        entrada = CrearItemSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        services.agregar_item(
            actor=request.user, plantilla=plantilla, **entrada.validated_data
        )
        return Response(PlantillaChecklistSerializer(plantilla).data, status=201)

    @action(
        detail=True,
        methods=["patch"],
        url_path=r"items/(?P<item_id>[^/.]+)",
    )
    def actualizar_item(self, request, pk=None, item_id=None):
        plantilla = get_object_or_404(PlantillaChecklist, pk=pk)
        item = get_object_or_404(plantilla.items, pk=item_id)
        entrada = ActualizarItemSerializer(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        services.actualizar_item(actor=request.user, item=item, **entrada.validated_data)
        return Response(PlantillaChecklistSerializer(plantilla).data)


class ChecklistEmpleadoView(APIView):
    """La tarjeta de la ficha: onboarding si la relación está activa, offboarding si dado de baja.

    Se resuelve el empleado por el selector de empleados para respetar el scope de la ficha
    (§7). La creación del proceso es perezosa (primera apertura), por eso un GET puede crear
    la fila: es idempotente y es el disparador que define la spec ("aparece en la ficha").
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, empleado_id=None):
        empleado = get_object_or_404(
            empleados_selectors.empleados_visibles_para(usuario=request.user), pk=empleado_id
        )
        relacion_activa = empleado.relacion_activa
        if relacion_activa is not None:
            relacion, tipo = relacion_activa, TipoProceso.INGRESO
        else:
            # Dado de baja: offboarding de la última relación finalizada.
            relacion = empleado.relaciones.filter(estado=EstadoRelacion.FINALIZADA).first()
            tipo = TipoProceso.EGRESO
        if relacion is None:
            return Response({"tarjeta": None})
        proceso = services.obtener_o_crear_proceso(
            actor=request.user, relacion=relacion, tipo_proceso=tipo
        )
        proceso = (
            ProcesoEmpleado.objects.select_related("relacion_laboral__empleado")
            .prefetch_related("items")
            .get(pk=proceso.pk)
        )
        return Response({"tarjeta": selectors.armar_tarjeta(proceso=proceso)})


class TildarItemChecklistView(APIView):
    """Tilda/destilda un ítem de ACCION de la tarjeta. Solo RRHH/Admin.

    Devuelve la tarjeta recalculada para que el front actualice progreso y colapso de una.
    """

    permission_classes = [IsAuthenticated, _SoloRRHH]

    def post(self, request, empleado_id=None, item_id=None):
        item = get_object_or_404(
            ItemProceso.objects.select_related("proceso__relacion_laboral__empleado"),
            pk=item_id,
            proceso__relacion_laboral__empleado_id=empleado_id,
        )
        entrada = TildarItemSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        services.tildar_item(
            actor=request.user, item=item, hecho=entrada.validated_data["hecho"]
        )
        proceso = (
            ProcesoEmpleado.objects.select_related("relacion_laboral__empleado")
            .prefetch_related("items")
            .get(pk=item.proceso_id)
        )
        return Response({"tarjeta": selectors.armar_tarjeta(proceso=proceso)})
