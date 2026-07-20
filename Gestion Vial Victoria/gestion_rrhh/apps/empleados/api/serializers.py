"""Contrato I/O de empleados (§11). Serializers de entrada y salida separados:
la entrada valida forma (R12); la escritura y las reglas viven en services.py.
"""
from rest_framework import serializers

from common import archivos, roles

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


# Campos que solo ven RRHH/Admin y el propio titular (A3). Tres familias: identidad
# (dni/cuil/fecha_nacimiento), contacto personal (telefono/direccion/contacto_emergencia)
# y datos sensibles (obra_social/art son salud; id_huella es biométrico). `observaciones`
# entra porque es texto libre de RRHH: ahí termina lo que no cabe en ningún campo.
# Fuera de la lista queda lo que un Supervisor necesita para operar: nombre, legajo, email,
# educación, exento_marcacion, y toda la relación laboral (empresa/sector/puesto/ingreso).
CAMPOS_PII = frozenset(
    {
        "dni",
        "cuil",
        "fecha_nacimiento",
        "telefono",
        "direccion",
        "contacto_emergencia",
        "obra_social",
        "art",
        "id_huella",
        "observaciones",
    }
)


def puede_ver_pii(*, usuario, empleado) -> bool:
    """RRHH/Admin ven todo; el resto, solo su propia ficha.

    El Supervisor ve la dotación entera (lo decide `selectors.empleados_visibles_para`),
    pero verla no es lo mismo que ver el DNI y la dirección de cada persona: el scope dice
    *a quiénes*, esto dice *cuánto* de cada uno. Al titular no se le oculta lo suyo —
    esconderle su propio DNI no protege a nadie y rompe la autoconsulta.
    """
    if usuario is None or not usuario.is_authenticated:
        return False
    return usuario.tiene_rol(roles.ADMIN, roles.RRHH) or empleado.usuario_id == usuario.id


class EmpleadoSerializer(serializers.ModelSerializer):
    relaciones = RelacionLaboralSerializer(many=True, read_only=True)
    nombre_completo = serializers.CharField(read_only=True)
    activo = serializers.BooleanField(read_only=True)

    def to_representation(self, instance):
        """Recorta el PII según el rol de quien pregunta (A3).

        Se filtra acá y no con dos serializers distintos para que la lista de campos siga
        siendo una sola: dos clases paralelas se desincronizan al primer campo nuevo, y el
        que se olvide de agregar en la versión reducida se filtra sin que nadie lo note.

        Falla cerrada: sin `request` en el contexto no hay a quién preguntarle el rol, así
        que se oculta. Todas las views pasan el contexto; si aparece un llamador que no lo
        hace, va a ver campos faltantes —ruidoso y del lado seguro— en vez de exponer PII.
        """
        datos = super().to_representation(instance)
        usuario = getattr(self.context.get("request"), "user", None)
        if puede_ver_pii(usuario=usuario, empleado=instance):
            return datos
        for campo in CAMPOS_PII:
            datos.pop(campo, None)
        return datos

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
    """Forma del respaldo (R12: la forma acá, las reglas en services). Regla en common."""
    error = archivos.errores_de_archivo(archivo)
    if error:
        raise serializers.ValidationError(error)
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
