"""Views flacas (§11): autentican, validan forma, delegan en service/selector.

Dos superficies:
- **ABM de plantillas** (`/onboarding/plantillas/`): Configuración. Escritura RRHH/Admin.
- **Tarjeta de la ficha** (`/empleados/{id}/checklist/`): anidada bajo el empleado, pero la
  vista vive acá para no invertir la dependencia (empleados NO conoce a onboarding). Lectura
  para quien puede ver la ficha; tildar, RRHH/Admin.
"""
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.empleados import selectors as empleados_selectors
from apps.empleados.models import EstadoRelacion
from common import roles
from common.permissions import RolRequerido

from .. import selectors, services
from ..models import ItemProceso, PlantillaChecklist, ProcesoEmpleado, TipoProceso
from .serializers import (
    ActualizarItemSerializer,
    CrearItemSerializer,
    CrearPlantillaSerializer,
    IniciarProcesoSerializer,
    PlantillaChecklistSerializer,
    TildarItemSerializer,
)

_SoloRRHH = RolRequerido(roles.ADMIN, roles.RRHH)


class PlantillaChecklistViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Configuración interna de plantillas: lectura y escritura solo RRHH/Admin."""

    serializer_class = PlantillaChecklistSerializer
    permission_classes = [_SoloRRHH]

    def get_queryset(self):
        return selectors.plantillas_visibles(filtros=self.request.query_params)

    def create(self, request):
        entrada = CrearPlantillaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        plantilla = services.crear_plantilla(actor=request.user, **entrada.validated_data)
        return Response(PlantillaChecklistSerializer(plantilla).data, status=201)

    @action(detail=True, methods=["post"])
    def publicar(self, request, pk=None):
        plantilla = services.publicar_plantilla(
            actor=request.user,
            plantilla=get_object_or_404(PlantillaChecklist, pk=pk),
        )
        return Response(PlantillaChecklistSerializer(plantilla).data)

    @action(detail=True, methods=["post"])
    def archivar(self, request, pk=None):
        plantilla = services.archivar_plantilla(
            actor=request.user,
            plantilla=get_object_or_404(PlantillaChecklist, pk=pk),
        )
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

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "item_id",
                OpenApiTypes.INT,
                OpenApiParameter.PATH,
                description="ID del ítem de la plantilla.",
            )
        ]
    )
    @action(
        detail=True,
        methods=["patch"],
        url_path=r"items/(?P<item_id>\d+)",
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
    (§7). GET es lectura pura; el proceso se inicia de forma explícita e idempotente con
    POST, para que una consulta o un crawler nunca produzcan estado de negocio.
    """

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), _SoloRRHH()]

    def _empleado(self, request, empleado_id):
        return get_object_or_404(
            empleados_selectors.empleados_visibles_para(usuario=request.user), pk=empleado_id
        )

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, empleado_id=None):
        empleado = self._empleado(request, empleado_id)
        relacion_activa = empleado.relacion_activa
        if relacion_activa is not None:
            relacion, tipo = relacion_activa, TipoProceso.INGRESO
        else:
            # Dado de baja: offboarding de la última relación finalizada.
            relacion = empleado.relaciones.filter(estado=EstadoRelacion.FINALIZADA).first()
            tipo = TipoProceso.EGRESO
        if relacion is None:
            return Response({"tarjeta": None})
        proceso = (
            ProcesoEmpleado.objects.select_related("relacion_laboral__empleado")
            .prefetch_related("items")
            .filter(relacion_laboral=relacion, tipo_proceso=tipo)
            .first()
        )
        if proceso is None:
            return Response(
                {
                    "tarjeta": None,
                    "puede_iniciar": request.user.tiene_rol(roles.ADMIN, roles.RRHH),
                    "relacion_laboral": relacion.pk,
                    "tipo_proceso": tipo,
                }
            )
        return Response({"tarjeta": selectors.armar_tarjeta(proceso=proceso)})

    @extend_schema(
        request=IniciarProcesoSerializer,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request, empleado_id=None):
        empleado = self._empleado(request, empleado_id)
        entrada = IniciarProcesoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        relacion = entrada.validated_data["relacion_laboral"]
        tipo = entrada.validated_data["tipo_proceso"]
        if relacion.empleado_id != empleado.pk:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"relacion_laboral": "La relación no pertenece al empleado de la URL."}
            )
        if tipo == TipoProceso.INGRESO and relacion.estado != EstadoRelacion.ACTIVA:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"tipo_proceso": "El onboarding requiere una relación activa."}
            )
        if tipo == TipoProceso.EGRESO and relacion.estado != EstadoRelacion.FINALIZADA:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"tipo_proceso": "El offboarding requiere una relación finalizada."}
            )
        proceso = services.iniciar_proceso(
            actor=request.user,
            relacion=relacion,
            tipo_proceso=tipo,
        )
        proceso = (
            ProcesoEmpleado.objects.select_related("relacion_laboral__empleado")
            .prefetch_related("items")
            .get(pk=proceso.pk)
        )
        return Response({"tarjeta": selectors.armar_tarjeta(proceso=proceso)}, status=201)


class TildarItemChecklistView(APIView):
    """Tilda/destilda un ítem de ACCION de la tarjeta. Solo RRHH/Admin.

    Devuelve la tarjeta recalculada para que el front actualice progreso y colapso de una.
    """

    permission_classes = [IsAuthenticated, _SoloRRHH]

    @extend_schema(
        request=TildarItemSerializer,
        responses=OpenApiTypes.OBJECT,
    )
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
