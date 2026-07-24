"""Empleados: persona, relación laboral (historial + baja lógica) y documentos (§5).

Multiempresa (P1): la persona (`Empleado`) es única a nivel grupo; la pertenencia a
una empresa se da por `RelacionLaboral`. Baja lógica solo donde el dominio lo pide
(R10: se finaliza la relación, nunca DELETE físico); el resto se protege con PROTECT.
"""
from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Func, Q
from django.db.models.functions import Upper
from django.utils import timezone

from common import archivos
from common.models import ModeloBase

from .identificadores import normalizar_cuil, normalizar_dni, normalizar_id_huella


class Educacion(models.TextChoices):
    PRIMARIO_INCOMPLETO = "PRIMARIO_INCOMPLETO", "Primario incompleto"
    PRIMARIO_COMPLETO = "PRIMARIO_COMPLETO", "Primario completo"
    SECUNDARIO_INCOMPLETO = "SECUNDARIO_INCOMPLETO", "Secundario incompleto"
    SECUNDARIO_COMPLETO = "SECUNDARIO_COMPLETO", "Secundario completo"
    TERCIARIO = "TERCIARIO", "Terciario"
    UNIVERSITARIO = "UNIVERSITARIO", "Universitario"


class JornadaLegal(models.TextChoices):
    COMPLETA_8H = "COMPLETA_8H", "Completa (8h)"
    REDUCIDA_6H = "REDUCIDA_6H", "Reducida (6h)"
    MEDIA_4H = "MEDIA_4H", "Media (4h)"
    ROTATIVA = "ROTATIVA", "Rotativa"


class TipoContrato(models.TextChoices):
    INDETERMINADO = "INDETERMINADO", "Indeterminado"
    PLAZO_FIJO = "PLAZO_FIJO", "Plazo fijo"
    EVENTUAL = "EVENTUAL", "Eventual"
    TEMPORADA = "TEMPORADA", "Temporada"
    PASANTIA = "PASANTIA", "Pasantía"


class MotivoEgreso(models.TextChoices):
    RENUNCIA = "RENUNCIA", "Renuncia"
    FIN_CONTRATO = "FIN_CONTRATO", "Fin de contrato"
    DESPIDO = "DESPIDO", "Despido"
    JUBILACION = "JUBILACION", "Jubilación"
    MUDANZA = "MUDANZA", "Mudanza"
    OTRO = "OTRO", "Otro"


class EstadoRelacion(models.TextChoices):
    ACTIVA = "ACTIVA", "Activa"
    FINALIZADA = "FINALIZADA", "Finalizada"


def ruta_archivo_foto(instance: "Empleado", filename: str) -> str:
    return archivos.ruta_con_uuid("fotos", instance.pk or "nuevo", filename)


class Empleado(ModeloBase):
    """Persona única a nivel grupo (P1). El PII (dni/cuil) se expone solo a RRHH/Admin."""

    legajo = models.CharField(max_length=20, unique=True)
    foto = models.FileField(
        upload_to=ruta_archivo_foto,
        blank=True,
        help_text="Foto de perfil (imagen raster). Se sirve por endpoint protegido, no por "
        "URL directa. FileField y no ImageField para no atar el repo a Pillow.",
    )
    dni = models.CharField(max_length=9, unique=True, db_index=True)
    cuil = models.CharField(max_length=11, unique=True, null=True, blank=True)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    id_huella = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Ej. HUELLA-0042. Se guarda desde MVP1 para el matching biométrico futuro (P2).",
    )
    exento_marcacion = models.BooleanField(
        default=False,
        help_text="P2: empleados exonerados de marcar. En MVP1 es solo dato.",
    )
    educacion = models.CharField(max_length=25, choices=Educacion.choices, blank=True)
    contacto_emergencia = models.CharField(
        max_length=200, blank=True, help_text="Nombre · vínculo · teléfono (un solo campo en MVP1)."
    )
    obra_social = models.CharField(max_length=100, blank=True)
    art = models.CharField(
        max_length=100, blank=True, help_text="Aseguradora de riesgos del trabajo."
    )
    observaciones = models.TextField(blank=True)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="empleado",
        help_text="Solo si el empleado accede al sistema.",
    )

    class Meta:
        verbose_name = "empleado"
        verbose_name_plural = "empleados"
        ordering = ["apellido", "nombre"]
        constraints = [
            models.CheckConstraint(
                condition=Q(dni__regex=r"^[0-9]{6,9}$"),
                name="empleado_dni_normalizado",
            ),
            models.CheckConstraint(
                condition=Q(cuil__isnull=True) | Q(cuil__regex=r"^[0-9]{11}$"),
                name="empleado_cuil_normalizado",
            ),
            models.CheckConstraint(
                condition=(
                    Q(id_huella__isnull=True)
                    | (
                        ~Q(id_huella="")
                        & ~Q(id_huella__regex=r"(^\s)|(\s$)")
                        & Q(id_huella=Upper("id_huella"))
                    )
                ),
                name="empleado_huella_normalizada",
            ),
        ]

    def _normalizar_identificadores(self) -> None:
        errores = {}
        for campo, normalizador in (
            ("dni", normalizar_dni),
            ("cuil", normalizar_cuil),
            ("id_huella", normalizar_id_huella),
        ):
            try:
                setattr(self, campo, normalizador(getattr(self, campo)))
            except ValidationError as error:
                errores[campo] = error.messages
        if errores:
            raise ValidationError(errores)

    def _validar_fecha_nacimiento(self) -> None:
        self.fecha_nacimiento = self._meta.get_field("fecha_nacimiento").to_python(
            self.fecha_nacimiento
        )
        if self.fecha_nacimiento and self.fecha_nacimiento > timezone.localdate():
            raise ValidationError(
                {"fecha_nacimiento": "La fecha de nacimiento no puede estar en el futuro."}
            )

    def full_clean(self, *args, **kwargs):
        self._normalizar_identificadores()
        self._validar_fecha_nacimiento()
        return super().full_clean(*args, **kwargs)

    def save(self, *args, **kwargs):
        self._normalizar_identificadores()
        self._validar_fecha_nacimiento()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.apellido}, {self.nombre} (leg. {self.legajo})"

    @property
    def nombre_completo(self) -> str:
        """Formato de fichero: "Apellido, Nombre". Ordena y busca bien, se lee mal."""
        return f"{self.apellido}, {self.nombre}"

    @property
    def nombre_natural(self) -> str:
        """Cómo se nombra a una persona. Va en todo lo que se le muestra al usuario.

        El panel mezclaba los dos formatos en la misma pantalla —la lista de empleados
        decía "Carla Benítez" y la tarjeta de alertas "Benítez, Carla"— porque cada
        endpoint elegía por su cuenta. `nombre_completo` queda para orden y admin.
        """
        return f"{self.nombre} {self.apellido}"

    @property
    def relacion_activa(self) -> "RelacionLaboral | None":
        """La (única, por R1) relación ACTIVA en cualquier empresa, si existe.

        Se resuelve sobre `relaciones.all()` y no con `.filter()`: un `.filter()` sobre la
        relación inversa ignora el prefetch del selector y dispara una query POR EMPLEADO
        (N+1 en la lista, que serializa `activo` para los 25 de la página). `.all()` usa la
        caché si está, y si no cae, hace la misma única query que haría el `.filter()`.
        El orden es el del Meta (`-fecha_ingreso`), igual en la caché que en la base.
        """
        return next(
            (r for r in self.relaciones.all() if r.estado == EstadoRelacion.ACTIVA), None
        )

    @property
    def activo(self) -> bool:
        return self.relacion_activa is not None

    @property
    def empleado_auditado(self) -> "Empleado":
        """De quién habla un evento de auditoría sobre esta fila (ver `auditoria.services`)."""
        return self


class RelacionLaboral(ModeloBase):
    """Vínculo persona↔empresa con historial y supervisor actual.

    La persona puede tener muchas relaciones históricas, pero solo una activa en todo el
    grupo y ninguna vigencia puede solaparse con otra.
    """

    empleado = models.ForeignKey(
        Empleado, on_delete=models.PROTECT, related_name="relaciones"
    )
    empresa = models.ForeignKey(
        "organizacion.Empresa", on_delete=models.PROTECT, related_name="relaciones"
    )
    sector = models.ForeignKey(
        "organizacion.Sector",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="relaciones",
    )
    puesto = models.ForeignKey(
        "organizacion.Puesto",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="relaciones",
    )
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="relaciones_supervisadas",
        help_text="Supervisor actual de esta relación. Null si todavía no fue asignado.",
    )
    fecha_ingreso = models.DateField(help_text="Base de antigüedad (spec §1.7).")
    jornada_legal = models.CharField(max_length=15, choices=JornadaLegal.choices, blank=True)
    tipo_contrato = models.CharField(
        max_length=15, choices=TipoContrato.choices, default=TipoContrato.INDETERMINADO
    )
    fecha_vencimiento_contrato = models.DateField(null=True, blank=True)
    estado = models.CharField(
        max_length=10, choices=EstadoRelacion.choices, default=EstadoRelacion.ACTIVA
    )
    fecha_egreso = models.DateField(null=True, blank=True)
    motivo_egreso = models.CharField(max_length=30, choices=MotivoEgreso.choices, blank=True)

    class Meta:
        verbose_name = "relación laboral"
        verbose_name_plural = "relaciones laborales"
        ordering = ["-fecha_ingreso"]
        constraints = [
            # Una persona solo puede estar activa una vez en todo el grupo empresarial.
            models.UniqueConstraint(
                fields=["empleado"],
                condition=Q(estado=EstadoRelacion.ACTIVA),
                name="uniq_relacion_activa_por_empleado",
            ),
            # Respaldo en DB de la validación amigable del service. Los extremos son
            # inclusivos: egreso e ingreso el mismo día sí se pisan.
            ExclusionConstraint(
                name="excl_relaciones_solapadas_por_empleado",
                expressions=[
                    ("empleado", RangeOperators.EQUAL),
                    (
                        Func(
                            "fecha_ingreso",
                            "fecha_egreso",
                            RangeBoundary(inclusive_lower=True, inclusive_upper=True),
                            function="DATERANGE",
                            output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
            ),
            models.CheckConstraint(
                condition=Q(fecha_egreso__isnull=True)
                | Q(fecha_egreso__gte=models.F("fecha_ingreso")),
                name="relacion_fechas_validas",
            ),
            # Se instala NOT VALID para tolerar activas legadas sin catálogo. A partir de
            # la migración, toda fila activa nueva o modificada debe tener ambos valores.
            models.CheckConstraint(
                condition=Q(estado=EstadoRelacion.FINALIZADA)
                | (Q(sector__isnull=False) & Q(puesto__isnull=False)),
                name="relacion_activa_con_catalogos",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        estado=EstadoRelacion.ACTIVA,
                        fecha_egreso__isnull=True,
                        motivo_egreso="",
                    )
                    | (
                        Q(
                            estado=EstadoRelacion.FINALIZADA,
                            fecha_egreso__isnull=False,
                        )
                        & ~Q(motivo_egreso="")
                    )
                ),
                name="relacion_estado_baja_coherente",
            ),
        ]
        indexes = [
            models.Index(
                fields=["supervisor", "empleado"],
                condition=Q(estado=EstadoRelacion.ACTIVA),
                name="idx_rel_activa_supervisor",
            ),
        ]

    def __str__(self):
        return f"{self.empleado} @ {self.empresa} ({self.estado})"

    @property
    def empleado_auditado(self) -> Empleado:
        """La baja de una relación es un hecho de la historia de la persona (auditoría)."""
        return self.empleado

    @property
    def antiguedad_en_dias(self) -> int | None:
        """Propiedad derivada pura (§11): no toca otras tablas."""
        if not self.fecha_ingreso:
            return None
        fin = self.fecha_egreso or timezone.localdate()
        return (fin - self.fecha_ingreso).days


class TipoDocumento(ModeloBase):
    """Catálogo de tipos de documento con vencimiento (cierra gap #1): APTO_MEDICO, CNRT…"""

    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.CharField(max_length=255, blank=True)
    activo = models.BooleanField(default=True)
    # Vive acá y no en Parametro porque es un atributo del tipo: se borra con él y no hay
    # claves sueltas que se desincronicen del catálogo. Un tipo nuevo nace avisando a 30
    # días sin que nadie lo configure.
    dias_aviso = models.PositiveSmallIntegerField(
        default=30,
        validators=[MaxValueValidator(180)],
        help_text="Días de anticipación con que se avisa el vencimiento de este documento.",
    )

    class Meta:
        verbose_name = "tipo de documento"
        verbose_name_plural = "tipos de documento"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


def ruta_archivo_documento(instance: "DocumentoEmpleado", filename: str) -> str:
    return archivos.ruta_con_uuid("documentos", instance.empleado_id, filename)


class DocumentoEmpleado(ModeloBase):
    """Documento exigible en una relación laboral. Uno por tipo y relación (UNIQUE).

    `empleado` se conserva por compatibilidad y acceso directo, pero la pertenencia de
    dominio es la relación: un reingreso abre una nueva carpeta documental y vuelve a
    exigir cada tipo. La migración se detiene si un legado no puede atribuirse sin inventar
    datos; por eso la FK queda obligatoria también en el modelo y no hay filas ocultas.
    """

    empleado = models.ForeignKey(
        Empleado, on_delete=models.PROTECT, related_name="documentos"
    )
    relacion_laboral = models.ForeignKey(
        RelacionLaboral,
        on_delete=models.PROTECT,
        related_name="documentos",
    )
    tipo_documento = models.ForeignKey(
        TipoDocumento, on_delete=models.PROTECT, related_name="documentos"
    )
    numero = models.CharField(max_length=50, blank=True)
    fecha_vencimiento = models.DateField(
        null=True, blank=True, db_index=True, help_text="La query de alertas filtra por acá."
    )
    archivo = models.FileField(
        upload_to=ruta_archivo_documento,
        blank=True,
        help_text="Respaldo escaneado (PDF/imagen). Opcional: el control de vencimientos "
        "funciona con la fecha sola, y RRHH puede cargar el vencimiento antes de tener el "
        "scan. Se descarga solo por el endpoint protegido, nunca por URL directa.",
    )
    observaciones = models.TextField(blank=True)

    class Meta:
        verbose_name = "documento de empleado"
        verbose_name_plural = "documentos de empleados"
        ordering = ["empleado", "tipo_documento"]
        constraints = [
            models.UniqueConstraint(
                fields=["relacion_laboral", "tipo_documento"],
                name="uniq_documento_por_relacion_tipo",
            ),
            models.CheckConstraint(
                condition=Q(relacion_laboral__isnull=False),
                name="documento_relacion_requerida",
            ),
        ]

    def __str__(self):
        return f"{self.tipo_documento} de {self.empleado}"

    def clean(self):
        super().clean()
        if (
            self.relacion_laboral_id
            and self.empleado_id
            and self.relacion_laboral.empleado_id != self.empleado_id
        ):
            raise ValidationError(
                {
                    "relacion_laboral": (
                        "La relación laboral seleccionada no pertenece al empleado."
                    )
                }
            )

    @property
    def empleado_auditado(self) -> Empleado:
        """Cargar o borrar un documento es un hecho de la historia de la persona (auditoría)."""
        return self.empleado
