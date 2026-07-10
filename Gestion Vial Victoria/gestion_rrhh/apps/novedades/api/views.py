"""Views flacas (§11): autentican, validan forma, delegan en service/selector.

Lectura scopeada por selector. Carga y prórroga: rol operativo (Supervisor+). Las
transiciones que deciden si una novedad justifica jornadas (aprobar/rechazar/anular)
exigen RRHH/Admin (R11). Las transiciones NO son PATCH: son acciones explícitas (§8).
"""
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common import roles
from common.permissions import LecturaAutenticadaEscrituraPorRol, RolRequerido

from .. import selectors, services
from ..models import TipoNovedad
from .serializers import (
    ActualizarNovedadSerializer,
    CadenaSerializer,
    CrearNovedadSerializer,
    NovedadSerializer,
    ProrrogarSerializer,
    RechazarAnularSerializer,
    TipoNovedadSerializer,
)

_SoloRRHH = RolRequerido(roles.ADMIN, roles.RRHH)  # R11: aprobar/rechazar/anular
_Operativos = RolRequerido(roles.ADMIN, roles.RRHH, roles.SUPERVISOR)  # cargar/prorrogar/editar


class NovedadViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = NovedadSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve", "cadena"):
            return [IsAuthenticated()]  # el selector recorta el scope
        if self.action in ("aprobar", "rechazar", "anular"):
            return [_SoloRRHH()]
        return [_Operativos()]  # create, partial_update, prorrogar

    def get_queryset(self):
        # Sin colapsar: retrieve y las acciones deben poder resolver una prórroga por su id.
        return selectors.novedades_visibles_para(
            usuario=self.request.user, filtros=self.request.query_params, colapsar=False
        )

    def list(self, request):
        qs = selectors.novedades_visibles_para(
            usuario=request.user, filtros=request.query_params, colapsar=True
        )
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(NovedadSerializer(page, many=True).data)

    def create(self, request):
        entrada = CrearNovedadSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        novedad = services.crear_novedad(actor=request.user, datos=dict(entrada.validated_data))
        return Response(NovedadSerializer(novedad).data, status=201)

    def partial_update(self, request, pk=None):
        novedad = self.get_object()
        entrada = ActualizarNovedadSerializer(novedad, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        novedad = services.actualizar_novedad(
            actor=request.user, novedad=novedad, datos=dict(entrada.validated_data)
        )
        return Response(NovedadSerializer(novedad).data)

    @action(detail=True, methods=["post"])
    def aprobar(self, request, pk=None):
        novedad = services.aprobar_novedad(actor=request.user, novedad=self.get_object())
        return Response(NovedadSerializer(novedad).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        entrada = RechazarAnularSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        novedad = services.rechazar_novedad(
            actor=request.user, novedad=self.get_object(), **entrada.validated_data
        )
        return Response(NovedadSerializer(novedad).data)

    @action(detail=True, methods=["post"])
    def anular(self, request, pk=None):
        entrada = RechazarAnularSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        novedad = services.anular_novedad(
            actor=request.user, novedad=self.get_object(), **entrada.validated_data
        )
        return Response(NovedadSerializer(novedad).data)

    @action(detail=True, methods=["post"])
    def prorrogar(self, request, pk=None):
        entrada = ProrrogarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        prorroga = services.prorrogar_novedad(
            actor=request.user, novedad=self.get_object(), **entrada.validated_data
        )
        return Response(NovedadSerializer(prorroga).data, status=201)

    @action(detail=True, methods=["get"])
    def cadena(self, request, pk=None):
        data = selectors.cadena_de(novedad=self.get_object())
        return Response(CadenaSerializer(data).data)


class TipoNovedadViewSet(viewsets.ModelViewSet):
    """Catálogo de tipos de novedad: lectura para autenticados, escritura RRHH/Admin."""

    queryset = TipoNovedad.objects.all()
    serializer_class = TipoNovedadSerializer
    permission_classes = [LecturaAutenticadaEscrituraPorRol(roles.ADMIN, roles.RRHH)]
    filterset_fields = ("activo",)
    search_fields = ("nombre", "codigo")
    http_method_names = ["get", "post", "patch", "head", "options"]
