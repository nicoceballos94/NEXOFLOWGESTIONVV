"""Views flacas (§11): autentican, validan forma, delegan en service/selector.

Lectura scopeada por selector; escritura (alta/edición/baja/documentos) solo RRHH/Admin.
"""
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common import roles
from common.permissions import LecturaAutenticadaEscrituraPorRol, RolRequerido

from .. import selectors, services
from ..models import Empleado, TipoDocumento
from .serializers import (
    ActualizarDocumentoSerializer,
    ActualizarEmpleadoSerializer,
    CrearDocumentoSerializer,
    CrearEmpleadoSerializer,
    CrearRelacionSerializer,
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
        if (
            self.action in ("list", "retrieve", "documentos", "archivo_documento")
            and self.request.method == "GET"
        ):
            return [IsAuthenticated()]
        return [_SoloRRHH()]

    def get_queryset(self):
        return selectors.empleados_visibles_para(
            usuario=self.request.user, filtros=self.request.query_params
        )

    def _empleado_en_scope(self, pk) -> Empleado:
        """El empleado, pero solo si el usuario puede verlo (§7).

        Buscar con `Empleado.objects` saltea el scoping del selector: `list`/`retrieve` lo
        aplican vía `get_queryset()`, y cualquier acción que resuelva el empleado por su
        cuenta se lo perdía. Un usuario con rol Empleado podía pedir los documentos de
        cualquier otra persona (A2 del análisis de sistema). Con los archivos adjuntos eso
        pasaba de fuga de metadatos a descarga del apto médico ajeno.

        Se llama al selector sin filtros a propósito, y no a `get_queryset()`: los de la
        query string son para buscar en la lista, y acá darían 404 espurios (pedir
        `/empleados/5/documentos/?empresa=3` no debería esconder al empleado 5 por estar
        en otra empresa). Acá el único recorte que corresponde es el del rol.
        """
        return get_object_or_404(
            selectors.empleados_visibles_para(usuario=self.request.user), pk=pk
        )

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        # El contexto no es decorativo: `EmpleadoSerializer` recorta el PII según el rol de
        # `request.user` (A3) y sin él falla cerrado, devolviendo la ficha sin esos campos.
        return self.get_paginated_response(
            EmpleadoSerializer(page, many=True, context=self.get_serializer_context()).data
        )

    def create(self, request):
        entrada = CrearEmpleadoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = dict(entrada.validated_data)
        datos_relacion = datos.pop("relacion")
        empleado = services.crear_empleado(
            actor=request.user, datos_empleado=datos, datos_relacion=datos_relacion
        )
        return Response(
            EmpleadoSerializer(empleado, context=self.get_serializer_context()).data,
            status=201,
        )

    def partial_update(self, request, pk=None):
        empleado = get_object_or_404(Empleado, pk=pk)
        entrada = ActualizarEmpleadoSerializer(empleado, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        empleado = services.actualizar_empleado(
            actor=request.user, empleado=empleado, datos_empleado=dict(entrada.validated_data)
        )
        return Response(
            EmpleadoSerializer(empleado, context=self.get_serializer_context()).data
        )

    @action(detail=True, methods=["get", "post"])
    def documentos(self, request, pk=None):
        empleado = self._empleado_en_scope(pk)
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
        methods=["patch", "delete"],
        url_path=r"documentos/(?P<documento_id>[^/.]+)",
    )
    def documento(self, request, pk=None, documento_id=None):
        """Corregir/renovar (PATCH) o quitar (DELETE) un documento ya cargado."""
        empleado = self._empleado_en_scope(pk)
        documento = get_object_or_404(empleado.documentos, pk=documento_id)
        if request.method == "DELETE":
            services.eliminar_documento(actor=request.user, documento=documento)
            return Response(status=204)
        entrada = ActualizarDocumentoSerializer(documento, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        documento = services.actualizar_documento(
            actor=request.user, documento=documento, **entrada.validated_data
        )
        return Response(DocumentoEmpleadoSerializer(documento).data)

    @action(
        detail=True,
        methods=["get"],
        url_path=r"documentos/(?P<documento_id>[^/.]+)/archivo",
    )
    def archivo_documento(self, request, pk=None, documento_id=None):
        """Descarga del respaldo. La única puerta al binario (§7).

        `media/` no se sirve como estático justamente para que este endpoint sea el único
        camino: acá hay login, rol y scope de empleado; en el sistema de archivos no hay
        nada de eso. Un apto médico es un dato de salud y no puede colgar de una URL que
        cualquiera con el link pueda abrir.
        """
        empleado = self._empleado_en_scope(pk)
        documento = get_object_or_404(empleado.documentos, pk=documento_id)
        if not documento.archivo:
            raise Http404("El documento no tiene archivo de respaldo cargado.")
        # `as_attachment` fuerza la descarga en vez de que el navegador renderice: un SVG o
        # un HTML disfrazado de imagen no se ejecuta en el origen de la app.
        # El nombre real (UUID) no le sirve a nadie; se arma uno legible al vuelo.
        extension = documento.archivo.name.rsplit(".", 1)[-1]
        nombre = slugify(
            f"{documento.tipo_documento.nombre}-{empleado.apellido}-{empleado.legajo}"
        )
        return FileResponse(
            documento.archivo.open("rb"),
            as_attachment=True,
            filename=f"{nombre}.{extension}",
        )

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

    @action(detail=True, methods=["post"], url_path="relaciones")
    def crear_relacion(self, request, pk=None):
        """Alta de una nueva relación laboral (p. ej. reingreso). R1 valida en el service."""
        empleado = get_object_or_404(Empleado, pk=pk)
        entrada = CrearRelacionSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        relacion = services.crear_relacion_laboral(
            actor=request.user, empleado=empleado, **entrada.validated_data
        )
        return Response(RelacionLaboralSerializer(relacion).data, status=201)


class TipoDocumentoViewSet(viewsets.ModelViewSet):
    """Catálogo de tipos de documento: CRUD puro (§organizacion)."""

    queryset = TipoDocumento.objects.all()
    serializer_class = TipoDocumentoSerializer
    permission_classes = [LecturaAutenticadaEscrituraPorRol(roles.ADMIN, roles.RRHH)]
    filterset_fields = ("activo",)
    search_fields = ("nombre",)
    http_method_names = ["get", "post", "patch", "head", "options"]
