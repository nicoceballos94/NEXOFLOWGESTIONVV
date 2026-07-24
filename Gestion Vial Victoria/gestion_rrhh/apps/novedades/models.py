"""Novedades: faltas, licencias, vacaciones, accidentes, permisos y horas extra (§5, §6 bis).

Núcleo del MVP1 junto con `empleados`. La licencia prorrogable se modela como una
**cadena**: 1 novedad madre + N prórrogas (cada una un registro `Novedad` con
`novedad_origen` = SIEMPRE la madre, ver §6 bis). La vigencia efectiva de la cadena
es un dato calculado (selector `vigencia_efectiva`), nunca un campo editable: así la
fecha "total" y la cadena no pueden contradecirse.
"""
from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import Func, Q

from common import archivos
from common.models import ModeloBase


class EstadoNovedad(models.TextChoices):
    """Workflow canónico (§21). El 'Pendiente' del front equivale a REGISTRADA."""

    REGISTRADA = "REGISTRADA", "Registrada"
    EN_PROCESO = "EN_PROCESO", "En proceso"
    APROBADA = "APROBADA", "Aprobada"
    RECHAZADA = "RECHAZADA", "Rechazada"
    CERRADA = "CERRADA", "Cerrada"
    ANULADA = "ANULADA", "Anulada"


# Estados en los que una novedad ocupa el calendario del empleado. Solo RECHAZADA y ANULADA
# lo liberan: la rechazada nunca pasó y la anulada se borra de los hechos. Una CERRADA, en
# cambio, ya transcurrió — sigue ocupando su período y nada puede pisarla.
# Vive acá (y no en services) porque el ExclusionConstraint de abajo lo necesita.
OCUPAN_PERIODO = (
    EstadoNovedad.REGISTRADA,
    EstadoNovedad.EN_PROCESO,
    EstadoNovedad.APROBADA,
    EstadoNovedad.CERRADA,
)


class _RangoDeFechas(Func):
    """daterange(fecha_desde, fecha_hasta, '[]') para el ExclusionConstraint.

    Con `fecha_hasta` NULL, Postgres arma un rango sin límite superior — exactamente la
    semántica de la novedad abierta (licencia sin alta médica: corre sin fin).
    """

    function = "DATERANGE"
    output_field = DateRangeField()


class ClasificacionNovedad(models.TextChoices):
    """Clasificación (no workflow) de faltas y licencias. En el front: 'Validado/Injustificado'."""

    JUSTIFICADA = "JUSTIFICADA", "Justificada"
    INJUSTIFICADA = "INJUSTIFICADA", "Injustificada"


class TipoNovedad(ModeloBase):
    """Catálogo de tipos con sus flags de comportamiento (§5).

    Los flags gobiernan las reglas: `justifica_ausencia` (cubre una jornada AUSENTE en la
    fase de asistencias), `ocupa_periodo` (no puede convivir con otra novedad en las mismas
    fechas), `requiere_certificado` (alerta si falta tras X días), `admite_prorroga`
    (habilita la cadena §6 bis) y `requiere_cantidad_horas` (HORAS_EXTRA, P4).

    `justifica_ausencia` y `ocupa_periodo` son distintos y no hay que confundirlos: una FALTA
    ocupa el día del empleado (no puede haber además una licencia ese día) pero NO justifica
    la ausencia. Las horas extra son al revés: no ocupan el día, conviven con lo que haya.
    """

    codigo = models.SlugField(
        max_length=30, unique=True, help_text="Ej. LICENCIA_MEDICA, HORAS_EXTRA."
    )
    nombre = models.CharField(max_length=100)
    justifica_ausencia = models.BooleanField(default=False)
    ocupa_periodo = models.BooleanField(
        default=False,
        help_text="El tipo toma el día del empleado: dos novedades con este flag no pueden "
        "convivir en el mismo período (falta, licencia, accidente, vacaciones, permiso).",
    )
    requiere_certificado = models.BooleanField(default=False)
    admite_prorroga = models.BooleanField(default=False)
    requiere_cantidad_horas = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "tipo de novedad"
        verbose_name_plural = "tipos de novedad"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Novedad(ModeloBase):
    """Un evento de RRHH sobre un empleado. Las prórrogas son también Novedad (ver §6 bis)."""

    empleado = models.ForeignKey(
        "empleados.Empleado", on_delete=models.PROTECT, related_name="novedades", db_index=True
    )
    relacion_laboral = models.ForeignKey(
        "empleados.RelacionLaboral",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="novedades",
        help_text="Contexto empresa/contrato; por defecto la relación activa del empleado.",
    )
    tipo_novedad = models.ForeignKey(
        TipoNovedad, on_delete=models.PROTECT, related_name="novedades"
    )
    fecha_desde = models.DateField(db_index=True)
    fecha_hasta = models.DateField(
        null=True, blank=True, help_text="Null = abierta (p. ej. licencia sin alta médica)."
    )
    cantidad_horas = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Solo tipos con requiere_cantidad_horas (HORAS_EXTRA manual, P4).",
    )
    estado = models.CharField(
        max_length=12, choices=EstadoNovedad.choices, default=EstadoNovedad.REGISTRADA
    )
    clasificacion = models.CharField(
        max_length=13, choices=ClasificacionNovedad.choices, blank=True
    )
    motivo = models.CharField(max_length=255, blank=True)
    observaciones = models.TextField(blank=True)
    fecha_aviso_empleado = models.DateField(
        null=True, blank=True, help_text="Cuándo avisó el empleado (del front)."
    )
    novedad_origen = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="prorrogas",
        db_index=True,
        help_text="Prórrogas: apunta SIEMPRE a la novedad madre de la cadena (§6 bis).",
    )
    requiere_praxis = models.BooleanField(
        default=False, help_text="Marca intervención de ART / seguimiento médico."
    )
    fecha_turno_praxis = models.DateField(null=True, blank=True)
    fecha_fin_estimada = models.DateField(null=True, blank=True)
    fecha_reintegro = models.DateField(null=True, blank=True)
    certificado_recibido_en = models.DateField(
        null=True, blank=True, help_text="Alerta 'sin certificado tras X días' (spec §1.3)."
    )
    generada_automaticamente = models.BooleanField(
        default=False, help_text="Distingue el cross-check automático de la carga manual."
    )
    aprobada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="novedades_aprobadas",
    )
    aprobada_en = models.DateTimeField(null=True, blank=True)
    ocupa_periodo = models.BooleanField(
        default=False,
        editable=False,
        help_text="Copia de tipo_novedad.ocupa_periodo, mantenida en save(). Existe solo "
        "porque un ExclusionConstraint no puede hacer JOIN a TipoNovedad: la regla de "
        "no-solapamiento necesita el flag como columna propia. No editar a mano.",
    )

    class Meta:
        verbose_name = "novedad"
        verbose_name_plural = "novedades"
        ordering = ["-fecha_desde", "-id"]
        constraints = [
            # Respaldo en la base de la regla que services._validar_sin_solapamiento valida
            # con un mensaje amigable: dos novedades que ocupan período no conviven. La
            # validación en Python puede perder una carrera entre requests concurrentes;
            # esto no. Requiere btree_gist (empleado_id WITH = dentro de un índice GiST).
            ExclusionConstraint(
                name="excl_novedades_solapadas_por_empleado",
                expressions=[
                    ("empleado", RangeOperators.EQUAL),
                    (
                        _RangoDeFechas(
                            "fecha_desde",
                            "fecha_hasta",
                            RangeBoundary(inclusive_lower=True, inclusive_upper=True),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(ocupa_periodo=True, estado__in=OCUPAN_PERIODO),
            )
        ]

    def __str__(self):
        return f"{self.tipo_novedad} de {self.empleado} ({self.fecha_desde})"

    def save(self, *args, **kwargs):
        # El flag se recalcula solo cuando el tipo puede haber cambiado: las transiciones de
        # estado guardan con update_fields acotado y no deben pagar un query extra por el tipo.
        campos = kwargs.get("update_fields")
        if campos is None or "tipo_novedad" in campos:
            self.ocupa_periodo = self.tipo_novedad.ocupa_periodo
        super().save(*args, **kwargs)

    @property
    def es_prorroga(self) -> bool:
        return self.novedad_origen_id is not None

    @property
    def empleado_auditado(self) -> "Empleado":  # noqa: F821
        """De quién habla un evento de auditoría sobre esta novedad (ver `auditoria.services`).

        Los eventos de adjuntos y de prórrogas se asientan sobre la novedad, así que también
        aterrizan en la ficha de la persona por este camino.
        """
        return self.empleado


def ruta_archivo_adjunto(instance: "AdjuntoNovedad", filename: str) -> str:
    return archivos.ruta_con_uuid("novedades", instance.novedad_id, filename)


class AdjuntoNovedad(ModeloBase):
    """Respaldo de un hecho: el certificado de la licencia, los estudios del accidente.

    Cuelga de la NOVEDAD y no del empleado, a propósito: el certificado de la licencia de
    marzo no es "un documento de la persona", es de esa licencia. De ahí sale la bitácora
    sin inventar nada — cada novedad conserva lo suyo, y las novedades no se borran nunca
    (se anulan). Por eso acá, al revés que en `empleados.DocumentoEmpleado`:

    - No hay UNIQUE ni "uno vigente por tipo": una licencia puede juntar el certificado, la
      prórroga del médico y tres estudios. Todos conviven.
    - Nada se pisa al agregar: el apto médico viejo es basura, un certificado viejo es
      historia.
    - No hay vencimiento: un certificado no vence, describe algo que ya pasó.

    Cada prórroga es una Novedad, así que los adjuntos caen en el eslabón que corresponde y
    la cadena queda con la cronología real de la licencia.
    """

    novedad = models.ForeignKey(
        Novedad, on_delete=models.PROTECT, related_name="adjuntos", db_index=True
    )
    archivo = models.FileField(upload_to=ruta_archivo_adjunto)
    nombre_original = models.CharField(
        max_length=255,
        help_text="El nombre con el que se subió. En disco el archivo es un UUID, pero en "
        "una bitácora saber que un adjunto era 'radiografia.jpg' y otro 'certificado.pdf' "
        "es justamente el dato: acá no hay un tipo que lo diga, como sí lo hay en los "
        "documentos del empleado.",
    )
    descripcion = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "adjunto de novedad"
        verbose_name_plural = "adjuntos de novedades"
        ordering = ["creado_en", "id"]  # bitácora: en orden de llegada

    def __str__(self):
        return f"{self.nombre_original} ({self.novedad})"
