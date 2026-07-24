"""Onboarding y offboarding: checklists de ingreso/egreso de personas (CU-29 / CU-30).

Dos mitades:
- **Plantilla** (`PlantillaChecklist` + `ItemPlantilla`): lo que RRHH configura una vez
  por empresa y tipo de proceso. Es un ABM, vive en Configuración.
- **Proceso** (`ProcesoEmpleado` + `ItemProceso`): la tarjeta de un empleado concreto.
  Se crea perezosamente al abrirse en la ficha (onboarding tras el alta; offboarding
  cuando la relación ya está dada de baja), así `empleados` no depende de esta app.

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

from common.models import ModeloBase


class TipoProceso(models.TextChoices):
    INGRESO = "INGRESO", "Onboarding (ingreso)"
    EGRESO = "EGRESO", "Offboarding (egreso)"


class TipoItem(models.TextChoices):
    ACCION = "ACCION", "Acción (se tilda a mano)"
    DOCUMENTAL = "DOCUMENTAL", "Documental (enlazado a un documento del legajo)"


class PlantillaChecklist(ModeloBase):
    """Checklist configurable, una activa por (empresa, tipo de proceso).

    El checklist puede diferir entre Vial Victoria y Premocor (decisión de negocio de la
    spec), por eso cuelga de la empresa. La baja es lógica (`activa`): una plantilla vieja
    no se borra porque hay `ItemProceso` que la fotografiaron.
    """

    empresa = models.ForeignKey(
        "organizacion.Empresa", on_delete=models.PROTECT, related_name="plantillas_checklist"
    )
    tipo_proceso = models.CharField(max_length=10, choices=TipoProceso.choices)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "plantilla de checklist"
        verbose_name_plural = "plantillas de checklist"
        ordering = ["empresa", "tipo_proceso"]
        constraints = [
            # Una sola plantilla ACTIVA por (empresa, tipo) — índice único parcial, mismo
            # patrón que la relación laboral activa. Puede haber plantillas viejas inactivas.
            models.UniqueConstraint(
                fields=["empresa", "tipo_proceso"],
                condition=models.Q(activa=True),
                name="uniq_plantilla_activa_por_empresa_tipo",
            )
        ]

    def __str__(self):
        return f"{self.get_tipo_proceso_display()} · {self.empresa}"


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


class ProcesoEmpleado(ModeloBase):
    """La tarjeta de checklist de un empleado, anclada a una RELACIÓN laboral.

    Se ancla a `relacion_laboral` y no al empleado: el onboarding es por ingreso a una
    empresa, así el reingreso (caso DAMIAN, 2 relaciones) no pisa el checklist anterior.
    Se crea perezosamente la primera vez que se abre en la ficha.

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
            # ingreso. Es el ancla del get_or_create perezoso del service.
            models.UniqueConstraint(
                fields=["relacion_laboral", "tipo_proceso"],
                name="uniq_proceso_por_relacion_tipo",
            )
        ]

    def __str__(self):
        return f"{self.get_tipo_proceso_display()} · {self.relacion_laboral}"


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
