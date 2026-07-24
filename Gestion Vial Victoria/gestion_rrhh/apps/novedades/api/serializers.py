"""Contrato I/O de novedades (§8, §11). Entrada valida forma (R12); las reglas van en services.

La salida expone, para las cadenas madre, `cantidad_prorrogas` y `vigencia_efectiva`
calculados (§6 bis), que el front usa para el badge y la línea de tiempo de la licencia.
"""
import re
from datetime import timedelta

from django.db import transaction
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.empleados.models import RelacionLaboral
from common import archivos, roles

from .. import selectors
from ..confidencialidad import CAMPOS_CONFIDENCIALES_NOVEDAD
from ..models import AdjuntoNovedad, Novedad, TipoNovedad


# ---------- Catálogo ----------
class TipoNovedadSerializer(serializers.ModelSerializer):
    _CAMPOS_SEMANTICOS = (
        "codigo",
        "justifica_ausencia",
        "ocupa_periodo",
        "requiere_certificado",
        "admite_prorroga",
        "requiere_cantidad_horas",
    )

    class Meta:
        model = TipoNovedad
        fields = (
            "id",
            "codigo",
            "nombre",
            "justifica_ausencia",
            "ocupa_periodo",
            "requiere_certificado",
            "admite_prorroga",
            "requiere_cantidad_horas",
            "activo",
        )

    def validate_codigo(self, value):
        codigo = (value or "").strip().upper().replace("-", "_")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", codigo):
            raise serializers.ValidationError(
                "Use letras mayúsculas, números y guion bajo; debe empezar con letra."
            )
        return codigo

    def validate(self, attrs):
        instance = self.instance
        if instance is not None and instance.novedades.exists():
            errores = {
                campo: "No se modifica después de usar el tipo en una novedad."
                for campo in self._CAMPOS_SEMANTICOS
                if campo in attrs and attrs[campo] != getattr(instance, campo)
            }
            if errores:
                raise serializers.ValidationError(errores)
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        # Cierra la carrera validate→save: si una novedad empezó a usar el tipo en el
        # medio, se vuelve a comprobar con la fila del catálogo bloqueada.
        bloqueado = TipoNovedad.objects.select_for_update().get(pk=instance.pk)
        if bloqueado.novedades.exists():
            errores = {
                campo: "No se modifica después de usar el tipo en una novedad."
                for campo in self._CAMPOS_SEMANTICOS
                if campo in validated_data
                and validated_data[campo] != getattr(bloqueado, campo)
            }
            if errores:
                raise serializers.ValidationError(errores)
        return super().update(bloqueado, validated_data)


# ---------- Salida ----------
class NovedadSerializer(serializers.ModelSerializer):
    tipo_novedad_codigo = serializers.CharField(source="tipo_novedad.codigo", read_only=True)
    tipo_novedad_nombre = serializers.CharField(source="tipo_novedad.nombre", read_only=True)
    empleado_nombre = serializers.CharField(source="empleado.nombre_natural", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    es_prorroga = serializers.BooleanField(read_only=True)
    cantidad_prorrogas = serializers.SerializerMethodField()
    vigencia_efectiva = serializers.SerializerMethodField()

    class Meta:
        model = Novedad
        fields = (
            "id",
            "empleado",
            "empleado_nombre",
            "relacion_laboral",
            "tipo_novedad",
            "tipo_novedad_codigo",
            "tipo_novedad_nombre",
            "fecha_desde",
            "fecha_hasta",
            "cantidad_horas",
            "estado",
            "estado_display",
            "clasificacion",
            "motivo",
            "observaciones",
            "motivo_rechazo",
            "motivo_anulacion",
            "fecha_aviso_empleado",
            "novedad_origen",
            "es_prorroga",
            "requiere_praxis",
            "fecha_turno_praxis",
            "fecha_fin_estimada",
            "fecha_reintegro",
            "certificado_recibido_en",
            "generada_automaticamente",
            "tomada_por",
            "tomada_en",
            "aprobada_por",
            "aprobada_en",
            "rechazada_por",
            "rechazada_en",
            "anulada_por",
            "anulada_en",
            "cerrada_por",
            "cerrada_en",
            "cantidad_prorrogas",
            "vigencia_efectiva",
        )

    def get_cantidad_prorrogas(self, obj) -> int:
        if obj.es_prorroga:
            return 0
        return selectors.cantidad_prorrogas(obj)

    @extend_schema_field(
        {
            "type": "object",
            "nullable": True,
            "properties": {
                "desde": {"type": "string", "format": "date", "nullable": True},
                "hasta": {"type": "string", "format": "date", "nullable": True},
            },
        }
    )
    def get_vigencia_efectiva(self, obj):
        if obj.es_prorroga:
            return None
        return selectors.vigencia_efectiva(obj)

    def to_representation(self, instance):
        """El Supervisor opera fechas/estados, no diagnósticos ni textos médicos.

        RRHH/Admin ven el detalle completo y el titular conserva acceso a sus propios
        datos. Sin request en el contexto se falla cerrado.
        """
        datos = super().to_representation(instance)
        request = self.context.get("request")
        usuario = getattr(request, "user", None)
        puede_ver = bool(
            usuario
            and usuario.is_authenticated
            and (
                usuario.tiene_rol(roles.ADMIN, roles.RRHH)
                or instance.empleado.usuario_id == usuario.id
            )
        )
        if puede_ver:
            return datos
        for campo in CAMPOS_CONFIDENCIALES_NOVEDAD:
            datos.pop(campo, None)
        return datos


# ---------- Entrada ----------
class CrearNovedadSerializer(serializers.ModelSerializer):
    # D4: el front puede seguir cargando "fecha + días"; el serializer calcula fecha_hasta.
    dias = serializers.IntegerField(required=False, min_value=1, write_only=True)
    relacion_laboral = serializers.PrimaryKeyRelatedField(
        queryset=RelacionLaboral.objects.all(), required=False
    )

    class Meta:
        model = Novedad
        fields = (
            "empleado",
            "relacion_laboral",
            "tipo_novedad",
            "fecha_desde",
            "fecha_hasta",
            "dias",
            "cantidad_horas",
            "clasificacion",
            "motivo",
            "observaciones",
            "fecha_aviso_empleado",
            "requiere_praxis",
            "fecha_turno_praxis",
            "fecha_fin_estimada",
            "fecha_reintegro",
            "certificado_recibido_en",
        )

    def validate(self, data):
        dias = data.pop("dias", None)
        if not data.get("fecha_hasta") and dias:
            data["fecha_hasta"] = data["fecha_desde"] + timedelta(days=dias - 1)
        return data


class ActualizarNovedadSerializer(serializers.ModelSerializer):
    """Edición de una novedad REGISTRADA. No cambia empleado ni el estado (eso son acciones)."""

    class Meta:
        model = Novedad
        fields = (
            "tipo_novedad",
            "fecha_desde",
            "fecha_hasta",
            "cantidad_horas",
            "clasificacion",
            "motivo",
            "observaciones",
            "fecha_aviso_empleado",
            "requiere_praxis",
            "fecha_turno_praxis",
            "fecha_fin_estimada",
            "fecha_reintegro",
            "certificado_recibido_en",
        )


class ProrrogarSerializer(serializers.Serializer):
    fecha_hasta_nueva = serializers.DateField()
    motivo = serializers.CharField(required=False, allow_blank=True, default="")
    certificado_recibido_en = serializers.DateField(required=False, allow_null=True)


class RechazarAnularSerializer(serializers.Serializer):
    motivo = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=500,
    )


class CerrarNovedadSerializer(serializers.Serializer):
    """Una novedad abierta necesita recibir su fin al cerrarse."""

    fecha_hasta = serializers.DateField(required=False)


class AdjuntoNovedadSerializer(serializers.ModelSerializer):
    """Salida de la bitácora. El `archivo` no se expone crudo: la ruta de MEDIA_ROOT no le
    sirve a nadie desde afuera (no hay URL pública que la resuelva) y filtra la
    organización del disco. Se expone el endpoint protegido."""

    archivo_url = serializers.SerializerMethodField()
    subido_por = serializers.CharField(source="creado_por.username", read_only=True, default=None)

    class Meta:
        model = AdjuntoNovedad
        fields = ("id", "novedad", "nombre_original", "descripcion", "archivo_url",
                  "subido_por", "creado_en")

    def get_archivo_url(self, obj) -> str:
        return f"/api/v1/novedades/{obj.novedad_id}/adjuntos/{obj.id}/archivo/"


class CrearAdjuntoSerializer(serializers.Serializer):
    archivo = serializers.FileField()
    descripcion = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_archivo(self, archivo):
        error = archivos.errores_de_archivo(archivo)
        if error:
            raise serializers.ValidationError(error)
        return archivo


class _VigenciaSerializer(serializers.Serializer):
    desde = serializers.DateField(allow_null=True)
    hasta = serializers.DateField(allow_null=True)


class CadenaSerializer(serializers.Serializer):
    """Salida de GET /novedades/{id}/cadena/ (§6 bis)."""

    madre = NovedadSerializer()
    prorrogas = NovedadSerializer(many=True)
    vigencia_efectiva = _VigenciaSerializer()
    dias_totales = serializers.IntegerField(allow_null=True)
