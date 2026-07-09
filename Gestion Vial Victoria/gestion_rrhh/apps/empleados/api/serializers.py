"""Contrato I/O de empleados (§11). Serializers de entrada y salida separados:
la entrada valida forma (R12); la escritura y las reglas viven en services.py.
"""
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

    class Meta:
        model = DocumentoEmpleado
        fields = (
            "id",
            "empleado",
            "tipo_documento",
            "tipo_documento_nombre",
            "numero",
            "fecha_vencimiento",
            "observaciones",
        )
        read_only_fields = ("empleado",)


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
    relacion = CrearRelacionSerializer(write_only=True)

    class Meta:
        model = Empleado
        fields = (
            "legajo",
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


class CrearDocumentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentoEmpleado
        fields = ("tipo_documento", "numero", "fecha_vencimiento", "observaciones")
