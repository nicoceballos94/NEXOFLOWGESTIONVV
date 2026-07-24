"""Onboarding y offboarding: checklists de ingreso/egreso de personas (CU-29 / CU-30).

Dos mitades:
- **Plantilla** (`PlantillaChecklist` + `ItemPlantilla`): lo que RRHH configura una vez
  por empresa y tipo de proceso. Es un ABM, vive en Configuración.
- **Proceso** (`ProcesoEmpleado` + `ItemProceso`): la tarjeta de una relación concreta.
  Se inicia con un POST explícito e idempotente (onboarding tras el alta; offboarding
  tras la baja), así una lectura nunca produce cambios.

Dos tipos de ítem (spec CU-29):
- **ACCION**: se tilda a mano; queda la constancia de quién y cuándo (`ItemProceso`).
- **DOCUMENTAL**: NO se tilda. Queda "hecho" cuando existe el `DocumentoEmpleado` de ese
  tipo con archivo adjunto. Una sola fuente de verdad (el documento); ese estado se
  calcula en el selector, nunca se guarda, para que no pueda contradecirse.

`ItemProceso` es una **foto** de la plantilla al momento de arrancar: si mañana RRHH saca
un renglón, no le borra el checklist ya cargado a nadie (constancia, sobre todo en egreso).
"""
from django.conf import settings
from django.db import models
from django.db.models.functions import Coalesce

from common.models import ModeloBase


class TipoProceso(models.TextChoices):
    INGRESO = "INGRESO", "Onboarding (ingreso)"
    EGRESO = "EGRESO", "Offboarding (egreso)"


class TipoItem(models.TextChoices):
    ACCION = "ACCION", "Acción (se tilda a mano)"
    DOCUMENTAL = "DOCUMENTAL", "Documental (enlazado a un documento del legajo)"


class EstadoPlantilla(models.TextChoices):
    BORRADOR = "BORRADOR", "Borrador"
    PUBLICADA = "PUBLICADA", "Publicada"
    ARCHIVADA = "ARCHIVADA", "Archivada"


class PlantillaChecklist(ModeloBase):
    """Checklist versionado por empresa, sector opcional y tipo de proceso.

    `sector=None` es el respaldo general de la empresa. Una versión publicada es
    inmutable; una nueva definición nace como borrador y al publicarse archiva la anterior.
    """

    empresa = models.ForeignKey(
        "organizacion.Empresa", on_delete=models.PROTECT, related_name="plantillas_checklist"
    )
    sector = models.ForeignKey(
        "organizacion.Sector",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="plantillas_checklist",
        help_text="Sector al que aplica. Null es una plantilla general de respaldo.",
    )
    tipo_proceso = models.CharField(max_length=10, choices=TipoProceso.choices)
    version = models.PositiveSmallIntegerField(default=1, editable=False)
    estado = models.CharField(
        max_length=10,
        choices=EstadoPlantilla.choices,
        default=EstadoPlantilla.BORRADOR,
    )

    class Meta:
        verbose_name = "plantilla de checklist"
        verbose_name_plural = "plantillas de checklist"
        ordering = ["empresa", "tipo_proceso"]
        constraints = [
            models.UniqueConstraint(
                models.F("empresa"),
                Coalesce("sector", models.Value(0)),
                models.F("tipo_proceso"),
                models.F("version"),
                name="uniq_version_plantilla_por_alcance",
            ),
            models.UniqueConstraint(
                models.F("empresa"),
                Coalesce("sector", models.Value(0)),
                models.F("tipo_proceso"),
                condition=models.Q(estado=EstadoPlantilla.PUBLICADA),
                name="uniq_plantilla_publicada_por_alcance",
            ),
            models.UniqueConstraint(
                models.F("empresa"),
                Coalesce("sector", models.Value(0)),
                models.F("tipo_proceso"),
                condition=models.Q(estado=EstadoPlantilla.BORRADOR),
                name="uniq_plantilla_borrador_por_alcance",
            ),
        ]

    def __str__(self):
        alcance = self.sector or "General"
        return (
            f"{self.get_tipo_proceso_display()} · {self.empresa} · {alcance} "
            f"(v{self.version})"
        )

    @property
    def activa(self) -> bool:
        """Compatibilidad de salida: una plantilla activa es una versión publicada."""
        return self.estado == EstadoPlantilla.PUBLICADA

    @property
    def empleado_auditado(self):
        """La configuración no pertenece al legajo de una persona."""
        return None


class ItemPlantilla(ModeloBase):
    """Un renglón de la plantilla: "Alta AFIP/ARCA", "Uniforme", "Devolución notebook"…"""

    plantilla = models.ForeignKey(
        PlantillaChecklist, on_delete=models.CASCADE, related_name="items"
    )
    orden = models.PositiveSmallIntegerField(
        default=0, help_text="Posición del renglón en la lista (menor primero)."
    )
    etiqueta = models.CharField(max_length=120)
    tipo_item = models.CharField(
        max_length=12, choices=TipoItem.choices, default=TipoItem.ACCION
    )
    tipo_documento = models.ForeignKey(
        "empleados.TipoDocumento",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="items_checklist",
        help_text="Solo para ítems DOCUMENTAL: el tipo de documento del legajo que lo completa.",
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ítem de plantilla"
        verbose_name_plural = "ítems de plantilla"
        ordering = ["plantilla", "orden", "id"]
        constraints = [
            # Coherencia tipo↔documento: DOCUMENTAL exige tipo_documento; ACCION lo prohíbe.
            # La validación amigable va igual en el serializer (§12 R12); esto es la red en DB.
            models.CheckConstraint(
                name="item_documental_exige_tipo_documento",
                condition=(
                    models.Q(tipo_item="DOCUMENTAL", tipo_documento__isnull=False)
                    | models.Q(tipo_item="ACCION", tipo_documento__isnull=True)
                ),
            )
        ]

    def __str__(self):
        return f"{self.etiqueta} ({self.get_tipo_item_display()})"

    @property
    def empleado_auditado(self):
        """La configuración no pertenece al legajo de una persona."""
        return None


class ProcesoEmpleado(ModeloBase):
    """La tarjeta de checklist de un empleado, anclada a una RELACIÓN laboral.

    Se ancla a `relacion_laboral` y no al empleado: el onboarding es por ingreso a una
    empresa, así el reingreso (caso DAMIAN, 2 relaciones) no pisa el checklist anterior.
    Se inicia mediante una escritura explícita e idempotente.

    NO guarda un campo "completado": la compleción se calcula en vivo (ítems hechos / total)
    porque un ítem DOCUMENTAL se completa al cargar un documento desde la app `empleados`,
    que no conoce a esta app. Un timestamp acá se desincronizaría; el selector es la verdad,
    y el "cuándo se completó" se deriva del máximo momento de los ítems.
    """

    relacion_laboral = models.ForeignKey(
        "empleados.RelacionLaboral", on_delete=models.PROTECT, related_name="procesos_checklist"
    )
    tipo_proceso = models.CharField(max_length=10, choices=TipoProceso.choices)
    plantilla = models.ForeignKey(
        PlantillaChecklist,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="procesos",
        help_text="Plantilla fotografiada al crear el proceso (referencia; puede quedar null).",
    )

    class Meta:
        verbose_name = "proceso de checklist"
        verbose_name_plural = "procesos de checklist"
        ordering = ["-creado_en"]
        constraints = [
            # Un solo proceso por (relación, tipo): no se abren dos onboarding para el mismo
            # ingreso. Es el ancla del inicio idempotente del service.
            models.UniqueConstraint(
                fields=["relacion_laboral", "tipo_proceso"],
                name="uniq_proceso_por_relacion_tipo",
            )
        ]

    def __str__(self):
        return f"{self.get_tipo_proceso_display()} · {self.relacion_laboral}"

    @property
    def empleado_auditado(self):
        return self.relacion_laboral.empleado
class ItemProceso(ModeloBase):
    """Foto de un renglón de la plantilla para un proceso concreto, con su estado.

    Guarda una copia de la definición (etiqueta/tipo/tipo_documento) para que cambiar la
    plantilla no reescriba checklists ya en curso. El estado se guarda SOLO para ACCION
    (tildado manual con constancia); el estado de los DOCUMENTAL se calcula en el selector
    mirando si existe el documento con archivo — nunca se persiste acá.
    """

    proceso = models.ForeignKey(
        ProcesoEmpleado, on_delete=models.CASCADE, related_name="items"
    )
    item_plantilla = models.ForeignKey(
        ItemPlantilla,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="items_proceso",
        help_text="Renglón de origen (referencia); puede quedar null si la plantilla cambia.",
    )
    orden = models.PositiveSmallIntegerField(default=0)
    etiqueta = models.CharField(max_length=120)
    tipo_item = models.CharField(max_length=12, choices=TipoItem.choices)
    tipo_documento = models.ForeignKey(
        "empleados.TipoDocumento",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="items_proceso",
        help_text="Foto del tipo de documento para ítems DOCUMENTAL (el que los completa).",
    )
    # Estado — solo aplica a ítems ACCION. Los DOCUMENTAL se derivan del documento (selector).
    completado = models.BooleanField(default=False)
    completado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Quién tildó el ítem de acción (constancia).",
    )
    completado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "ítem de proceso"
        verbose_name_plural = "ítems de proceso"
        ordering = ["proceso", "orden", "id"]

    def __str__(self):
        return f"{self.etiqueta} · {self.proceso}"

    @property
    def empleado_auditado(self):
        """De quién habla un evento de auditoría sobre este ítem (ver `auditoria.services`).

        El checklist cuelga de la RELACIÓN (para que el reingreso no pise el anterior), así
        que hasta la persona hay dos saltos.
        """
        return self.proceso.relacion_laboral.empleado
