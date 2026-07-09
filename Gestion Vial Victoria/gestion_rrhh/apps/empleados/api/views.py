"""Views flacas (§11): autentican, validan forma, delegan en service/selector.

Lectura scopeada por selector; escritura (alta/edición/baja/documentos) solo RRHH/Admin.
"""
from django.shortcuts import get_object_or_404
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common import roles
from common.permissions import LecturaAutenticadaEscrituraPorRol, RolRequerido

from .. import selectors, services
from ..models import Empleado, TipoDocumento
from .serializers import (
    ActualizarEmpleadoSerializer,
    CrearDocumentoSerializer,
    CrearEmpleadoSerializer,
    DocumentoEmpleadoSerializer,
    EmpleadoSerializer,
    FinalizarRelacionSerializer,
    RelacionLaboralSerializer,
    TipoDocumentoSerializer,
)

_SoloRRHH = RolRequerido(roles.ADMIN, roles.RRHH)


class EmpleadoViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = EmpleadoSerializer

    def get_permissions(self):
        # Lectura: cualquier autenticado (el selector recorta el scope).
        # Escritura y acciones que mutan: RRHH/Admin.
        if self.action in ("list", "retrieve", "documentos") and self.request.method == "GET":
            return [IsAuthenticated()]
        return [_SoloRRHH()]

    def get_queryset(self):
        return selectors.empleados_visibles_para(
            usuario=self.request.user, filtros=self.request.query_params
        )

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(EmpleadoSerializer(page, many=True).data)

    def create(self, request):
        entrada = CrearEmpleadoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = dict(entrada.validated_data)
        datos_relacion = datos.pop("relacion")
        empleado = services.crear_empleado(
            actor=request.user, datos_empleado=datos, datos_relacion=datos_relacion
        )
        return Response(EmpleadoSerializer(empleado).data, status=201)

    def partial_update(self, request, pk=None):
        empleado = get_object_or_404(Empleado, pk=pk)
        entrada = ActualizarEmpleadoSerializer(empleado, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        empleado = services.actualizar_empleado(
            actor=request.user, empleado=empleado, datos_empleado=dict(entrada.validated_data)
        )
        return Response(EmpleadoSerializer(empleado).data)

    @action(detail=True, methods=["get", "post"])
    def documentos(self, request, pk=None):
        empleado = get_object_or_404(Empleado, pk=pk)
        if request.method == "GET":
            qs = empleado.documentos.select_related("tipo_documento")
            return Response(DocumentoEmpleadoSerializer(qs, many=True).data)
        entrada = CrearDocumentoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        documento = services.crear_documento(
            actor=request.user, empleado=empleado, **entrada.validated_data
        )
        return Response(DocumentoEmpleadoSerializer(documento).data, status=201)

    @action(
        detail=True,
        methods=["post"],
        url_path=r"relaciones/(?P<relacion_id>[^/.]+)/finalizar",
    )
    def finalizar_relacion(self, request, pk=None, relacion_id=None):
        empleado = get_object_or_404(Empleado, pk=pk)
        relacion = get_object_or_404(empleado.relaciones, pk=relacion_id)
        entrada = FinalizarRelacionSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        relacion = services.finalizar_relacion(
            actor=request.user, relacion=relacion, **entrada.validated_data
        )
        return Response(RelacionLaboralSerializer(relacion).data)


class TipoDocumentoViewSet(viewsets.ModelViewSet):
    """Catálogo de tipos de documento: CRUD puro (§organizacion)."""

    queryset = TipoDocumento.objects.all()
    serializer_class = TipoDocumentoSerializer
    permission_classes = [LecturaAutenticadaEscrituraPorRol(roles.ADMIN, roles.RRHH)]
    filterset_fields = ("activo",)
    search_fields = ("nombre",)
    http_method_names = ["get", "post", "patch", "head", "options"]
