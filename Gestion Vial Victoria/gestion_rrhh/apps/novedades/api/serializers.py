"""Contrato I/O de novedades (§8, §11). Entrada valida forma (R12); las reglas van en services.

La salida expone, para las cadenas madre, `cantidad_prorrogas` y `vigencia_efectiva`
calculados (§6 bis), que el front usa para el badge y la línea de tiempo de la licencia.
"""
from datetime import timedelta

from rest_framework import serializers

from common import archivos

from .. import selectors
from ..models import AdjuntoNovedad, Novedad, TipoNovedad


# ---------- Catálogo ----------
class TipoNovedadSerializer(serializers.ModelSerializer):
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


# ---------- Salida ----------
class NovedadSerializer(serializers.ModelSerializer):
    tipo_novedad_codigo = serializers.CharField(source="tipo_novedad.codigo", read_only=True)
    tipo_novedad_nombre = serializers.CharField(source="tipo_novedad.nombre", read_only=True)
    empleado_nombre = serializers.CharField(source="empleado.nombre_completo", read_only=True)
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
            "fecha_aviso_empleado",
            "novedad_origen",
            "es_prorroga",
            "requiere_praxis",
            "fecha_turno_praxis",
            "fecha_fin_estimada",
            "fecha_reintegro",
            "certificado_recibido_en",
            "generada_automaticamente",
            "aprobada_por",
            "aprobada_en",
            "cantidad_prorrogas",
            "vigencia_efectiva",
        )

    def get_cantidad_prorrogas(self, obj) -> int:
        if obj.es_prorroga:
            return 0
        return selectors.cantidad_prorrogas(obj)

    def get_vigencia_efectiva(self, obj):
        if obj.es_prorroga:
            return None
        return selectors.vigencia_efectiva(obj)


# ---------- Entrada ----------
class CrearNovedadSerializer(serializers.ModelSerializer):
    # D4: el front puede seguir cargando "fecha + días"; el serializer calcula fecha_hasta.
    dias = serializers.IntegerField(required=False, min_value=1, write_only=True)

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
    motivo = serializers.CharField(required=False, allow_blank=True, default="")


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
