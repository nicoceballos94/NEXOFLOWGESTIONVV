"""Contrato I/O de empleados (§11). Serializers de entrada y salida separados:
la entrada valida forma (R12); la escritura y las reglas viven en services.py.
"""
from django.conf import settings
from rest_framework import serializers

from ..models import (
    DocumentoEmpleado,
    Empleado,
    RelacionLaboral,
    TipoDocumento,
)


# ---------- Salida ----------
class RelacionLaboralSerializer(serializers.ModelSerializer):
    antiguedad_en_dias = serializers.IntegerField(read_only=True)

    class Meta:
        model = RelacionLaboral
        fields = (
            "id",
            "empresa",
            "sector",
            "puesto",
            "fecha_ingreso",
            "jornada_legal",
            "tipo_contrato",
            "fecha_vencimiento_contrato",
            "estado",
            "fecha_egreso",
            "motivo_egreso",
            "antiguedad_en_dias",
        )


class EmpleadoSerializer(serializers.ModelSerializer):
    relaciones = RelacionLaboralSerializer(many=True, read_only=True)
    nombre_completo = serializers.CharField(read_only=True)
    activo = serializers.BooleanField(read_only=True)

    class Meta:
        model = Empleado
        fields = (
            "id",
            "legajo",
            "dni",
            "cuil",
            "nombre",
            "apellido",
            "nombre_completo",
            "fecha_nacimiento",
            "telefono",
            "email",
            "direccion",
            "id_huella",
            "exento_marcacion",
            "educacion",
            "contacto_emergencia",
            "obra_social",
            "art",
            "observaciones",
            "usuario",
            "activo",
            "relaciones",
        )


class DocumentoEmpleadoSerializer(serializers.ModelSerializer):
    tipo_documento_nombre = serializers.CharField(source="tipo_documento.nombre", read_only=True)
    tiene_archivo = serializers.SerializerMethodField()
    archivo_url = serializers.SerializerMethodField()

    class Meta:
        model = DocumentoEmpleado
        fields = (
            "id",
            "empleado",
            "tipo_documento",
            "tipo_documento_nombre",
            "numero",
            "fecha_vencimiento",
            "tiene_archivo",
            "archivo_url",
            "observaciones",
        )
        # `archivo` no se expone crudo: la ruta de MEDIA_ROOT no le sirve a nadie desde
        # afuera (no hay URL pública que la resuelva) y filtra la organización del disco.
        read_only_fields = ("empleado",)

    def get_tiene_archivo(self, obj) -> bool:
        return bool(obj.archivo)

    def get_archivo_url(self, obj) -> str | None:
        """Endpoint protegido de descarga, no la ruta del disco."""
        if not obj.archivo:
            return None
        return f"/api/v1/empleados/{obj.empleado_id}/documentos/{obj.id}/archivo/"


class TipoDocumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoDocumento
        fields = ("id", "nombre", "descripcion", "activo")


# ---------- Entrada ----------
class CrearRelacionSerializer(serializers.ModelSerializer):
    """Datos para crear una relación laboral (junto al alta, o suelta en un reingreso)."""

    class Meta:
        model = RelacionLaboral
        fields = (
            "empresa",
            "sector",
            "puesto",
            "fecha_ingreso",
            "jornada_legal",
            "tipo_contrato",
            "fecha_vencimiento_contrato",
        )


class CrearEmpleadoSerializer(serializers.ModelSerializer):
    """El `legajo` no se acepta del cliente: lo asigna el service (ver `_asignar_legajo`)."""

    relacion = CrearRelacionSerializer(write_only=True)

    class Meta:
        model = Empleado
        fields = (
            "dni",
            "cuil",
            "nombre",
            "apellido",
            "fecha_nacimiento",
            "telefono",
            "email",
            "direccion",
            "id_huella",
            "exento_marcacion",
            "educacion",
            "contacto_emergencia",
            "obra_social",
            "art",
            "observaciones",
            "usuario",
            "relacion",
        )


class ActualizarEmpleadoSerializer(serializers.ModelSerializer):
    """Edición de la ficha; las relaciones se gestionan por sus propios endpoints."""

    class Meta:
        model = Empleado
        fields = (
            "cuil",
            "nombre",
            "apellido",
            "fecha_nacimiento",
            "telefono",
            "email",
            "direccion",
            "id_huella",
            "exento_marcacion",
            "educacion",
            "contacto_emergencia",
            "obra_social",
            "art",
            "observaciones",
            "usuario",
        )


class FinalizarRelacionSerializer(serializers.Serializer):
    fecha_egreso = serializers.DateField()
    motivo_egreso = serializers.ChoiceField(
        choices=RelacionLaboral._meta.get_field("motivo_egreso").choices
    )


def _validar_archivo(archivo):
    """Extensión y peso del respaldo (R12: la forma se valida acá, no en el service).

    La extensión se mira, no el contenido: para saber de verdad si un PDF es un PDF hace
    falta leer los magic bytes (python-magic/libmagic, dependencia binaria). Es una
    concesión consciente — el archivo nunca se ejecuta ni se sirve como HTML, se descarga
    como adjunto, así que el peor caso es un archivo inútil cargado por RRHH, no un XSS.
    """
    if archivo in (None, ""):
        return archivo
    nombre = getattr(archivo, "name", "") or ""
    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if extension not in settings.DOCUMENTO_EXTENSIONES:
        raise serializers.ValidationError(
            f"Formato no admitido ('{extension or 'sin extensión'}'). "
            f"Se aceptan: {', '.join(settings.DOCUMENTO_EXTENSIONES)}."
        )
    if archivo.size > settings.DOCUMENTO_MAX_BYTES:
        tope_mb = settings.DOCUMENTO_MAX_BYTES / (1024 * 1024)
        real_mb = archivo.size / (1024 * 1024)
        raise serializers.ValidationError(
            f"El archivo pesa {real_mb:.1f} MB y el máximo es {tope_mb:.0f} MB. "
            f"Si es una foto, sacala con menos resolución o escaneala como PDF."
        )
    return archivo


class CrearDocumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoEmpleado
        fields = ("tipo_documento", "numero", "fecha_vencimiento", "archivo", "observaciones")

    def validate_archivo(self, archivo):
        return _validar_archivo(archivo)


class ActualizarDocumentoSerializer(serializers.ModelSerializer):
    """Corrección/renovación. El tipo no se edita (sería otro documento, no este)."""

    class Meta:
        model = DocumentoEmpleado
        fields = ("numero", "fecha_vencimiento", "archivo", "observaciones")

    def validate_archivo(self, archivo):
        return _validar_archivo(archivo)
