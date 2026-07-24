"""Views flacas (§11): autentican, validan forma, delegan en service/selector.

Lectura scopeada por selector; escritura (alta/edición/baja/documentos) solo RRHH/Admin.
"""
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from apps.auditoria.api.mixins import CatalogoAuditadoMixin
from apps.auditoria.services import Accion, registrar_evento
from common import roles
from common.permissions import (
    LecturaAutenticadaEscrituraPorRol,
    RolRequerido,
    usuario_tiene_rol,
)

from .. import selectors, services
from ..models import Empleado, TipoDocumento
from .consultas import BuscarEmpleadoPorDniSerializer
from .serializers import (
    ActualizarDocumentoSerializer,
    ActualizarEmpleadoSerializer,
    ActualizarFichaCompletaSerializer,
    ActualizarRelacionSerializer,
    AsignarSupervisorSerializer,
    CrearDocumentoSerializer,
    CrearEmpleadoSerializer,
    CrearRelacionSerializer,
    DocumentoEmpleadoSerializer,
    EmpleadoResumenSerializer,
    EmpleadoSerializer,
    FinalizarRelacionSerializer,
    RelacionLaboralSerializer,
    SubirFotoSerializer,
    TipoDocumentoSerializer,
)

_SoloRRHH = RolRequerido(roles.ADMIN, roles.RRHH)
_LecturaDocumentos = RolRequerido(roles.ADMIN, roles.RRHH, roles.EMPLEADO)


class _SoloRRHHSinServicio(BasePermission):
    """Consulta por identificador: nunca disponible para identidades de máquina."""

    message = "La búsqueda exacta por DNI requiere una identidad humana de RRHH/Admin."

    def has_permission(self, request, view):
        usuario = request.user
        if not usuario or not usuario.is_authenticated:
            return False
        if usuario.groups.filter(name=roles.SERVICIO).exists():
            return False
        return usuario_tiene_rol(usuario, (roles.ADMIN, roles.RRHH))


class EmpleadoViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Empleado.objects.none()
    serializer_class = EmpleadoSerializer

    def get_permissions(self):
        # Lectura: cualquier autenticado (el selector recorta el scope).
        # Escritura y acciones que mutan: RRHH/Admin.
        if self.action == "por_dni":
            return [_SoloRRHHSinServicio()]
        if (
            self.action in ("documentos", "archivo_documento")
            and self.request.method == "GET"
        ):
            # Supervisor opera personas/fechas de su equipo, no legajos documentales ni
            # binarios médicos. Empleado conserva lectura de sus propios documentos; el
            # selector de objeto aplica ese scope.
            return [_LecturaDocumentos()]
        if (
            self.action
            in ("list", "retrieve", "foto_archivo")
            and self.request.method == "GET"
        ):
            return [IsAuthenticated()]
        return [_SoloRRHH()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Empleado.objects.none()
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

    def _empleado_documental_en_scope(self, pk) -> Empleado:
        """RRHH/Admin ven legajos; un Empleado, exclusivamente el legajo propio.

        No se reutiliza el scope general porque una identidad legítimamente puede reunir
        los roles Supervisor y Empleado. En ese caso, el alcance de Supervisor sirve para
        operar su equipo, pero nunca amplía el acceso a documentos médicos.
        """
        usuario = self.request.user
        queryset = Empleado.objects.prefetch_related("relaciones")
        if not usuario.tiene_rol(roles.ADMIN, roles.RRHH):
            queryset = queryset.filter(usuario_id=usuario.id)
        return get_object_or_404(queryset, pk=pk)

    @extend_schema(responses=EmpleadoResumenSerializer(many=True))
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        # El listado nunca expone PII: la ficha completa pasa por `retrieve`, que además
        # deja el evento EMPLEADO_CONSULTADO.
        return self.get_paginated_response(
            EmpleadoResumenSerializer(
                page,
                many=True,
                context=self.get_serializer_context(),
            ).data
        )

    def retrieve(self, request, *args, **kwargs):
        empleado = self.get_object()
        datos = EmpleadoSerializer(
            empleado,
            context=self.get_serializer_context(),
        ).data
        registrar_evento(
            actor=request.user,
            accion=Accion.EMPLEADO_CONSULTADO,
            objeto=empleado,
            despues={},
        )
        return Response(datos)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "dni",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=True,
                description=(
                    "DNI completo. Acepta puntos, guiones o espacios de formato; "
                    "la coincidencia siempre es exacta."
                ),
            )
        ],
        responses={200: EmpleadoSerializer, 404: OpenApiTypes.OBJECT},
    )
    @action(detail=False, methods=["get"], url_path="por-dni")
    def por_dni(self, request):
        if len(request.query_params.getlist("dni")) != 1:
            raise ValidationError(
                {"dni": "Debe informarse exactamente un DNI completo."}
            )
        entrada = BuscarEmpleadoPorDniSerializer(data=request.query_params)
        entrada.is_valid(raise_exception=True)
        empleado = get_object_or_404(
            Empleado.objects.prefetch_related("relaciones"),
            dni=entrada.validated_data["dni"],
        )
        datos = EmpleadoSerializer(
            empleado,
            context=self.get_serializer_context(),
        ).data
        registrar_evento(
            actor=request.user,
            accion=Accion.EMPLEADO_CONSULTADO,
            objeto=empleado,
            despues={},
        )
        return Response(datos)

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

    @extend_schema(
        request=ActualizarFichaCompletaSerializer,
        responses={200: EmpleadoSerializer},
    )
    @action(detail=True, methods=["patch"], url_path="ficha")
    def actualizar_ficha(self, request, pk=None):
        """Guarda persona y asignación en una sola transacción."""
        empleado = get_object_or_404(Empleado, pk=pk)
        sobre = ActualizarFichaCompletaSerializer(data=request.data)
        sobre.is_valid(raise_exception=True)
        datos_empleado = sobre.validated_data.get("empleado", {})
        datos_relacion = sobre.validated_data.get("relacion", {})

        entrada_empleado = ActualizarEmpleadoSerializer(
            empleado,
            data=datos_empleado,
            partial=True,
        )
        entrada_empleado.is_valid(raise_exception=True)

        relacion = empleado.relacion_activa
        if datos_relacion and relacion is None:
            raise ValidationError(
                {"relacion": "El empleado no tiene una relación laboral activa."}
            )
        datos_relacion_validados = {}
        if relacion is not None and datos_relacion:
            entrada_relacion = ActualizarRelacionSerializer(
                relacion,
                data=datos_relacion,
                partial=True,
            )
            entrada_relacion.is_valid(raise_exception=True)
            datos_relacion_validados = dict(entrada_relacion.validated_data)

        empleado = services.actualizar_ficha_completa(
            actor=request.user,
            empleado=empleado,
            datos_empleado=dict(entrada_empleado.validated_data),
            relacion=relacion,
            datos_relacion=datos_relacion_validados,
        )
        empleado = Empleado.objects.prefetch_related(
            "relaciones__empresa",
            "relaciones__sector",
            "relaciones__puesto",
            "relaciones__supervisor",
        ).get(pk=empleado.pk)
        return Response(
            EmpleadoSerializer(
                empleado,
                context=self.get_serializer_context(),
            ).data
        )

    def _relacion_documental(self, empleado, relacion_solicitada=None):
        relaciones = list(empleado.relaciones.all())
        actual = next(
            (relacion for relacion in relaciones if relacion.estado == "ACTIVA"),
            relaciones[0] if relaciones else None,
        )
        if relacion_solicitada in (None, ""):
            return actual
        try:
            relacion_id = int(relacion_solicitada)
        except (TypeError, ValueError):
            raise ValidationError({"relacion": "Debe ser un id numérico."})
        elegida = next(
            (relacion for relacion in relaciones if relacion.id == relacion_id),
            None,
        )
        if elegida is None:
            raise Http404("La relación laboral no pertenece al empleado.")
        if (
            actual is not None
            and elegida.id != actual.id
            and not self.request.user.tiene_rol(roles.ADMIN, roles.RRHH)
        ):
            raise Http404("La relación laboral no está en el alcance del usuario.")
        return elegida

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "relacion",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                required=False,
                description="Relación laboral a consultar; el historial requiere RRHH/Admin.",
            )
        ]
    )
    @action(detail=True, methods=["get", "post"])
    def documentos(self, request, pk=None):
        empleado = (
            self._empleado_documental_en_scope(pk)
            if request.method == "GET"
            else self._empleado_en_scope(pk)
        )
        if request.method == "GET":
            relacion = self._relacion_documental(
                empleado, request.query_params.get("relacion")
            )
            if relacion is None:
                return Response([])
            qs = empleado.documentos.filter(relacion_laboral=relacion).select_related(
                "tipo_documento", "relacion_laboral"
            )
            return Response(DocumentoEmpleadoSerializer(qs, many=True).data)
        entrada = CrearDocumentoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        documento = services.crear_documento(
            actor=request.user, empleado=empleado, **entrada.validated_data
        )
        return Response(DocumentoEmpleadoSerializer(documento).data, status=201)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "documento_id",
                OpenApiTypes.INT,
                OpenApiParameter.PATH,
                description="ID del documento de la relación activa.",
            )
        ]
    )
    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"documentos/(?P<documento_id>\d+)",
    )
    def documento(self, request, pk=None, documento_id=None):
        """Corregir/renovar (PATCH) o quitar (DELETE) un documento ya cargado."""
        empleado = self._empleado_en_scope(pk)
        relacion_activa = empleado.relacion_activa
        if relacion_activa is None:
            raise Http404("El empleado no tiene una relación laboral activa.")
        documento = get_object_or_404(
            empleado.documentos,
            pk=documento_id,
            relacion_laboral=relacion_activa,
        )
        if request.method == "DELETE":
            services.eliminar_documento(actor=request.user, documento=documento)
            return Response(status=204)
        entrada = ActualizarDocumentoSerializer(documento, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        documento = services.actualizar_documento(
            actor=request.user, documento=documento, **entrada.validated_data
        )
        return Response(DocumentoEmpleadoSerializer(documento).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "documento_id",
                OpenApiTypes.INT,
                OpenApiParameter.PATH,
                description="ID del documento.",
            )
        ],
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    @action(
        detail=True,
        methods=["get"],
        url_path=r"documentos/(?P<documento_id>\d+)/archivo",
    )
    def archivo_documento(self, request, pk=None, documento_id=None):
        """Descarga del respaldo. La única puerta al binario (§7).

        `media/` no se sirve como estático justamente para que este endpoint sea el único
        camino: acá hay login, rol y scope de empleado; en el sistema de archivos no hay
        nada de eso. Un apto médico es un dato de salud y no puede colgar de una URL que
        cualquiera con el link pueda abrir.
        """
        empleado = self._empleado_documental_en_scope(pk)
        documentos = empleado.documentos.all()
        if not request.user.tiene_rol(roles.ADMIN, roles.RRHH):
            relacion = self._relacion_documental(empleado)
            documentos = documentos.filter(relacion_laboral=relacion)
        documento = get_object_or_404(documentos, pk=documento_id)
        if not documento.archivo:
            raise Http404("El documento no tiene archivo de respaldo cargado.")
        # `as_attachment` fuerza la descarga en vez de que el navegador renderice: un SVG o
        # un HTML disfrazado de imagen no se ejecuta en el origen de la app.
        # El nombre real (UUID) no le sirve a nadie; se arma uno legible al vuelo.
        extension = documento.archivo.name.rsplit(".", 1)[-1]
        nombre = slugify(
            f"{documento.tipo_documento.nombre}-{empleado.apellido}-{empleado.legajo}"
        )
        archivo = documento.archivo.open("rb")
        registrar_evento(
            actor=request.user,
            accion=Accion.DOCUMENTO_DESCARGADO,
            objeto=documento,
            despues={"archivo": documento.archivo.name},
        )
        return FileResponse(
            archivo,
            as_attachment=True,
            filename=f"{nombre}.{extension}",
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "relacion_id",
                OpenApiTypes.INT,
                OpenApiParameter.PATH,
                description="ID de la relación laboral activa.",
            )
        ]
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"relaciones/(?P<relacion_id>\d+)/finalizar",
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

    @extend_schema(
        request=ActualizarRelacionSerializer,
        responses={200: RelacionLaboralSerializer},
        parameters=[
            OpenApiParameter(
                "relacion_id",
                OpenApiTypes.INT,
                OpenApiParameter.PATH,
                description="ID de la relación laboral activa.",
            )
        ],
    )
    @action(
        detail=True,
        methods=["patch"],
        url_path=r"relaciones/(?P<relacion_id>\d+)",
    )
    def relacion(self, request, pk=None, relacion_id=None):
        """Actualiza sector/puesto/contrato sin falsear una baja y un reingreso."""
        empleado = get_object_or_404(Empleado, pk=pk)
        relacion = get_object_or_404(empleado.relaciones, pk=relacion_id)
        entrada = ActualizarRelacionSerializer(
            relacion,
            data=request.data,
            partial=True,
        )
        entrada.is_valid(raise_exception=True)
        relacion = services.actualizar_relacion_laboral(
            actor=request.user,
            relacion=relacion,
            datos=dict(entrada.validated_data),
        )
        return Response(RelacionLaboralSerializer(relacion).data)

    @extend_schema(
        request=AsignarSupervisorSerializer,
        responses={200: RelacionLaboralSerializer},
        parameters=[
            OpenApiParameter(
                "relacion_id",
                OpenApiTypes.INT,
                OpenApiParameter.PATH,
                description="ID de la relación laboral activa.",
            )
        ],
    )
    @action(
        detail=True,
        methods=["patch"],
        url_path=r"relaciones/(?P<relacion_id>\d+)/supervisor",
    )
    def supervisor_relacion(self, request, pk=None, relacion_id=None):
        """Asigna, reasigna o quita el supervisor de una relación activa."""
        empleado = get_object_or_404(Empleado, pk=pk)
        relacion = get_object_or_404(empleado.relaciones, pk=relacion_id)
        entrada = AsignarSupervisorSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        relacion = services.asignar_supervisor_relacion(
            actor=request.user,
            relacion=relacion,
            supervisor=entrada.validated_data["supervisor"],
        )
        return Response(RelacionLaboralSerializer(relacion).data)

    @action(detail=True, methods=["post", "delete"], url_path="foto")
    def foto(self, request, pk=None):
        """Setea (POST, multipart) o quita (DELETE) la foto de perfil. Solo RRHH/Admin.

        La escritura cae en `_SoloRRHH` por `get_permissions`; el scope de lectura no aplica
        acá porque solo RRHH/Admin llegan, y ellos ven a todos. Se resuelve el empleado sin
        el selector para no confundir "no está en tu scope" (404) con "no existe".
        """
        empleado = get_object_or_404(Empleado, pk=pk)
        if request.method == "DELETE":
            services.eliminar_foto_empleado(actor=request.user, empleado=empleado)
            return Response(status=204)
        entrada = SubirFotoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        empleado = services.guardar_foto_empleado(
            actor=request.user, empleado=empleado, foto=entrada.validated_data["foto"]
        )
        return Response(
            EmpleadoSerializer(empleado, context=self.get_serializer_context()).data
        )

    @action(detail=True, methods=["get"], url_path=r"foto/archivo")
    def foto_archivo(self, request, pk=None):
        """Sirve la foto de perfil. Como los documentos, es la única puerta al binario (§7):
        `media/` no se sirve como estático, así que acá hay login y scope.

        Va inline (`as_attachment=False`) porque esta imagen se **muestra** en la ficha; es
        seguro porque el serializer solo aceptó imágenes raster (ni PDF ni SVG).
        """
        empleado = self._empleado_en_scope(pk)
        if not empleado.foto:
            raise Http404("El empleado no tiene foto de perfil cargada.")
        extension = empleado.foto.name.rsplit(".", 1)[-1]
        nombre = slugify(f"foto-{empleado.apellido}-{empleado.legajo}")
        archivo = empleado.foto.open("rb")
        registrar_evento(
            actor=request.user,
            accion=Accion.FOTO_CONSULTADA,
            objeto=empleado,
            despues={},
        )
        return FileResponse(
            archivo,
            as_attachment=False,
            filename=f"{nombre}.{extension}",
        )

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


class TipoDocumentoViewSet(CatalogoAuditadoMixin, viewsets.ModelViewSet):
    """Catálogo de tipos de documento: CRUD puro (§organizacion)."""

    queryset = TipoDocumento.objects.all()
    serializer_class = TipoDocumentoSerializer
    permission_classes = [LecturaAutenticadaEscrituraPorRol(roles.ADMIN, roles.RRHH)]
    filterset_fields = ("activo",)
    search_fields = ("nombre",)
    http_method_names = ["get", "post", "patch", "head", "options"]
