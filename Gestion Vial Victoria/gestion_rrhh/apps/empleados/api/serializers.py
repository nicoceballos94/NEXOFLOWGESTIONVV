"""Contrato I/O de empleados (§11). Serializers de entrada y salida separados:
la entrada valida forma (R12); la escritura y las reglas viven en services.py.
"""
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from apps.organizacion.models import Empresa, Puesto, Sector
from apps.usuarios.models import Usuario
from common import archivos, roles

from ..identificadores import normalizar_cuil, normalizar_dni, normalizar_id_huella
from ..models import (
    DocumentoEmpleado,
    Empleado,
    RelacionLaboral,
    TipoDocumento,
)
from .campos import IdentificadorNormalizadoField


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
            "supervisor",
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
    relaciones = serializers.SerializerMethodField()
    nombre_completo = serializers.CharField(read_only=True)
    activo = serializers.BooleanField(read_only=True)
    tiene_foto = serializers.SerializerMethodField()
    foto_url = serializers.SerializerMethodField()

    def get_tiene_foto(self, obj) -> bool:
        return bool(obj.foto)

    def get_foto_url(self, obj) -> str | None:
        """Endpoint protegido, no la ruta del disco. La cara no es PII (§A3): un supervisor
        ve a su dotación, igual que ve el nombre. Fuera de `CAMPOS_PII` a propósito."""
        if not obj.foto:
            return None
        return f"/api/v1/empleados/{obj.id}/foto/archivo/"

    @extend_schema_field(RelacionLaboralSerializer(many=True))
    def get_relaciones(self, obj):
        """No filtra solo la persona: también recorta su historial para Supervisor."""
        relaciones = list(obj.relaciones.all())
        usuario = getattr(self.context.get("request"), "user", None)
        if (
            usuario
            and usuario.is_authenticated
            and usuario.tiene_rol(roles.SUPERVISOR)
            and not usuario.tiene_rol(roles.ADMIN, roles.RRHH)
            and obj.usuario_id != usuario.id
        ):
            relaciones = [
                relacion
                for relacion in relaciones
                if relacion.estado == "ACTIVA" and relacion.supervisor_id == usuario.id
            ]
        return RelacionLaboralSerializer(relaciones, many=True).data

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
            "tiene_foto",
            "foto_url",
            "relaciones",
        )


class EmpleadoResumenSerializer(EmpleadoSerializer):
    """Fila de listado sin PII.

    La ficha completa se obtiene por ``retrieve``, que además deja constancia de la
    consulta sensible. Si el listado devolviera los mismos campos que la ficha, sería
    posible leer DNI, domicilio o datos de salud sin pasar por ese evento.
    """

    class Meta(EmpleadoSerializer.Meta):
        # El correo personal también permite identificar/contactar a la persona. La ficha
        # lo conserva con su control por objeto; el listado masivo no lo necesita.
        campos_excluidos = CAMPOS_PII | {"email"}
        fields = tuple(
            campo
            for campo in EmpleadoSerializer.Meta.fields
            if campo not in (CAMPOS_PII | {"email"})
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
            "relacion_laboral",
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
        read_only_fields = ("empleado", "relacion_laboral")

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

    @staticmethod
    def _error_desactivacion(tipo):
        from apps.onboarding.models import EstadoPlantilla, TipoItem

        if tipo.items_checklist.filter(
            activo=True,
            tipo_item=TipoItem.DOCUMENTAL,
            plantilla__estado=EstadoPlantilla.PUBLICADA,
        ).exists():
            return (
                "No se puede desactivar: una plantilla publicada exige este documento. "
                "Publicá primero una nueva versión sin ese ítem."
            )

        items_pendientes = tipo.items_proceso.filter(
            tipo_item=TipoItem.DOCUMENTAL,
        ).select_related("proceso__relacion_laboral")
        for item in items_pendientes.iterator():
            completo = (
                DocumentoEmpleado.objects.filter(
                    relacion_laboral_id=item.proceso.relacion_laboral_id,
                    tipo_documento=tipo,
                )
                .exclude(archivo="")
                .exists()
            )
            if not completo:
                return (
                    "No se puede desactivar: existe un onboarding/offboarding iniciado "
                    "que todavía necesita este documento."
                )
        return None

    def validate(self, attrs):
        if (
            self.instance is not None
            and self.instance.activo
            and attrs.get("activo") is False
        ):
            error = self._error_desactivacion(self.instance)
            if error:
                raise serializers.ValidationError({"activo": error})
        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        bloqueado = TipoDocumento.objects.select_for_update().get(pk=instance.pk)
        if bloqueado.activo and validated_data.get("activo") is False:
            error = self._error_desactivacion(bloqueado)
            if error:
                raise serializers.ValidationError({"activo": error})
        return super().update(bloqueado, validated_data)


# ---------- Entrada ----------
class CrearRelacionSerializer(serializers.ModelSerializer):
    """Datos para crear una relación laboral (junto al alta, o suelta en un reingreso)."""

    empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.filter(activa=True))
    sector = serializers.PrimaryKeyRelatedField(queryset=Sector.objects.filter(activo=True))
    puesto = serializers.PrimaryKeyRelatedField(
        queryset=Puesto.objects.filter(activo=True, sector__activo=True)
    )

    class Meta:
        model = RelacionLaboral
        fields = (
            "empresa",
            "sector",
            "puesto",
            "supervisor",
            "fecha_ingreso",
            "jornada_legal",
            "tipo_contrato",
            "fecha_vencimiento_contrato",
        )

    def validate(self, attrs):
        sector = attrs["sector"]
        puesto = attrs["puesto"]
        if puesto.sector_id != sector.id:
            raise serializers.ValidationError(
                {"puesto": "El puesto seleccionado no pertenece al sector indicado."}
            )
        supervisor = attrs.get("supervisor")
        if supervisor is not None:
            if not supervisor.is_active:
                raise serializers.ValidationError(
                    {"supervisor": "No se puede asignar un usuario inactivo como supervisor."}
                )
            if supervisor.groups.filter(name=roles.SERVICIO).exists():
                raise serializers.ValidationError(
                    {
                        "supervisor": (
                            "Una identidad de Servicio no puede supervisar empleados."
                        )
                    }
                )
            if not supervisor.groups.filter(name=roles.SUPERVISOR).exists():
                raise serializers.ValidationError(
                    {
                        "supervisor": (
                            "El usuario asignado debe pertenecer al rol Supervisor."
                        )
                    }
                )
        vencimiento = attrs.get("fecha_vencimiento_contrato")
        if vencimiento and vencimiento < attrs["fecha_ingreso"]:
            raise serializers.ValidationError(
                {
                    "fecha_vencimiento_contrato": (
                        "El vencimiento del contrato no puede ser anterior al ingreso."
                    )
                }
            )
        return attrs


class CrearEmpleadoSerializer(serializers.ModelSerializer):
    """El `legajo` no se acepta del cliente: lo asigna el service (ver `_asignar_legajo`)."""

    dni = IdentificadorNormalizadoField(
        normalizador=normalizar_dni,
        max_length=9,
        validators=[
            UniqueValidator(
                queryset=Empleado.objects.all(),
                message="Ya existe un empleado con ese DNI.",
            )
        ],
    )
    cuil = IdentificadorNormalizadoField(
        normalizador=normalizar_cuil,
        max_length=11,
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[
            UniqueValidator(
                queryset=Empleado.objects.all(),
                message="Ya existe un empleado con ese CUIL.",
            )
        ],
    )
    id_huella = IdentificadorNormalizadoField(
        normalizador=normalizar_id_huella,
        max_length=50,
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[
            UniqueValidator(
                queryset=Empleado.objects.all(),
                message="Ya existe un empleado con ese identificador de huella.",
            )
        ],
    )
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

    def validate_fecha_nacimiento(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError(
                "La fecha de nacimiento no puede estar en el futuro."
            )
        return value


class ActualizarEmpleadoSerializer(serializers.ModelSerializer):
    """Edición de la ficha; las relaciones se gestionan por sus propios endpoints."""

    cuil = IdentificadorNormalizadoField(
        normalizador=normalizar_cuil,
        max_length=11,
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[
            UniqueValidator(
                queryset=Empleado.objects.all(),
                message="Ya existe un empleado con ese CUIL.",
            )
        ],
    )
    id_huella = IdentificadorNormalizadoField(
        normalizador=normalizar_id_huella,
        max_length=50,
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[
            UniqueValidator(
                queryset=Empleado.objects.all(),
                message="Ya existe un empleado con ese identificador de huella.",
            )
        ],
    )

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

    def validate_fecha_nacimiento(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError(
                "La fecha de nacimiento no puede estar en el futuro."
            )
        return value


class ActualizarRelacionSerializer(serializers.ModelSerializer):
    """Cambio de asignación vigente; la empresa y las fechas de vida laboral son inmutables."""

    sector = serializers.PrimaryKeyRelatedField(
        queryset=Sector.objects.filter(activo=True),
        required=False,
    )
    puesto = serializers.PrimaryKeyRelatedField(
        queryset=Puesto.objects.filter(activo=True, sector__activo=True),
        required=False,
    )

    class Meta:
        model = RelacionLaboral
        fields = (
            "sector",
            "puesto",
            "jornada_legal",
            "tipo_contrato",
            "fecha_vencimiento_contrato",
        )

    def validate(self, attrs):
        sector = attrs.get("sector", self.instance.sector)
        puesto = attrs.get("puesto", self.instance.puesto)
        if puesto is not None and sector is not None and puesto.sector_id != sector.id:
            raise serializers.ValidationError(
                {"puesto": "El puesto seleccionado no pertenece al sector indicado."}
            )
        vencimiento = attrs.get(
            "fecha_vencimiento_contrato",
            self.instance.fecha_vencimiento_contrato,
        )
        if vencimiento and vencimiento < self.instance.fecha_ingreso:
            raise serializers.ValidationError(
                {
                    "fecha_vencimiento_contrato": (
                        "El vencimiento del contrato no puede ser anterior al ingreso."
                    )
                }
            )
        return attrs


class ActualizarFichaCompletaSerializer(serializers.Serializer):
    """Sobre de la edición atómica de persona + asignación laboral vigente."""

    empleado = serializers.DictField(required=False)
    relacion = serializers.DictField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Informá al menos datos de empleado o de relación."
            )
        return attrs


class FinalizarRelacionSerializer(serializers.Serializer):
    fecha_egreso = serializers.DateField()
    motivo_egreso = serializers.ChoiceField(
        choices=RelacionLaboral._meta.get_field("motivo_egreso").choices
    )


class AsignarSupervisorSerializer(serializers.Serializer):
    """Asigna, reemplaza o quita el responsable de una relación activa."""

    supervisor = serializers.PrimaryKeyRelatedField(
        queryset=Usuario.objects.all(),
        allow_null=True,
    )

    def validate_supervisor(self, supervisor):
        if supervisor is None:
            return None
        if not supervisor.is_active:
            raise serializers.ValidationError(
                "No se puede asignar un usuario inactivo como supervisor."
            )
        if supervisor.groups.filter(name=roles.SERVICIO).exists():
            raise serializers.ValidationError(
                "Una identidad de Servicio no puede supervisar empleados."
            )
        if not supervisor.groups.filter(name=roles.SUPERVISOR).exists():
            raise serializers.ValidationError(
                "El usuario asignado debe pertenecer al rol Supervisor."
            )
        return supervisor


def _validar_archivo(archivo):
    """Forma del respaldo (R12: la forma acá, las reglas en services). Regla en common."""
    error = archivos.errores_de_archivo(archivo)
    if error:
        raise serializers.ValidationError(error)
    return archivo


class SubirFotoSerializer(serializers.Serializer):
    """Entrada de la foto de perfil (multipart). Valida solo forma (R12: imagen, tamaño)."""

    foto = serializers.FileField()

    def validate_foto(self, foto):
        error = archivos.errores_de_foto(foto)
        if error:
            raise serializers.ValidationError(error)
        return archivos.normalizar_foto(foto)


class CrearDocumentoSerializer(serializers.ModelSerializer):
    tipo_documento = serializers.PrimaryKeyRelatedField(
        queryset=TipoDocumento.objects.filter(activo=True)
    )

    def validate_cuil(self, valor):
        return (valor or "").strip() or None

    def validate_id_huella(self, valor):
        return (valor or "").strip() or None

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
