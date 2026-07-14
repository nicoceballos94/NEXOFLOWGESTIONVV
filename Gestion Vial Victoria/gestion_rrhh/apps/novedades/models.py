"""Novedades: faltas, licencias, vacaciones, accidentes, permisos y horas extra (§5, §6 bis).

Núcleo del MVP1 junto con `empleados`. La licencia prorrogable se modela como una
**cadena**: 1 novedad madre + N prórrogas (cada una un registro `Novedad` con
`novedad_origen` = SIEMPRE la madre, ver §6 bis). La vigencia efectiva de la cadena
es un dato calculado (selector `vigencia_efectiva`), nunca un campo editable: así la
fecha "total" y la cadena no pueden contradecirse.
"""
from django.conf import settings
from django.db import models

from common.models import ModeloBase


class EstadoNovedad(models.TextChoices):
    """Workflow canónico (§21). El 'Pendiente' del front equivale a REGISTRADA."""

    REGISTRADA = "REGISTRADA", "Registrada"
    EN_PROCESO = "EN_PROCESO", "En proceso"
    APROBADA = "APROBADA", "Aprobada"
    RECHAZADA = "RECHAZADA", "Rechazada"
    CERRADA = "CERRADA", "Cerrada"
    ANULADA = "ANULADA", "Anulada"


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

    class Meta:
        verbose_name = "novedad"
        verbose_name_plural = "novedades"
        ordering = ["-fecha_desde", "-id"]

    def __str__(self):
        return f"{self.tipo_novedad} de {self.empleado} ({self.fecha_desde})"

    @property
    def es_prorroga(self) -> bool:
        return self.novedad_origen_id is not None
