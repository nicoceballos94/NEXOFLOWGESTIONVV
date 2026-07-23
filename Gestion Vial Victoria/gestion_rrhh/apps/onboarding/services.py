"""Escritura de onboarding/offboarding: ABM de plantillas y avance de la tarjeta (§11-12).

Dos frentes:
- **ABM de plantillas** (Configuración): crear la plantilla por empresa+tipo y sus ítems.
  "Quitar" un ítem es baja lógica (`activo=False`), mismo criterio que los tipos de
  documento (CU-31); un ítem inactivo no se copia a procesos nuevos.
- **Avance de la tarjeta** (ficha): creación perezosa del proceso (foto de la plantilla) y
  tildado de ítems de ACCION con constancia. Los ítems DOCUMENTAL no se tildan acá: se
  completan solos al cargar su documento (lo resuelve el selector).
"""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import (
    ItemPlantilla,
    ItemProceso,
    PlantillaChecklist,
    ProcesoEmpleado,
    TipoItem,
)

# --- ABM de plantillas (Configuración) -------------------------------------------------

@transaction.atomic
def crear_plantilla(*, actor, empresa, tipo_proceso: str) -> PlantillaChecklist:
    """Crea la plantilla de una empresa+tipo. Error amigable antes del índice único parcial."""
    if PlantillaChecklist.objects.filter(
        empresa=empresa, tipo_proceso=tipo_proceso, activa=True
    ).exists():
        raise ValidationError(
            {"tipo_proceso": "Ya existe una plantilla activa para esta empresa y tipo de proceso."}
        )
    return PlantillaChecklist.objects.create(
        creado_por=actor, empresa=empresa, tipo_proceso=tipo_proceso
    )


def _validar_coherencia_item(*, tipo_item: str, tipo_documento) -> None:
    """DOCUMENTAL exige tipo de documento; ACCION lo prohíbe (el mismo check vive en DB)."""
    if tipo_item == TipoItem.DOCUMENTAL and tipo_documento is None:
        raise ValidationError(
            {"tipo_documento": "Un ítem documental debe enlazar un tipo de documento del legajo."}
        )
    if tipo_item == TipoItem.ACCION and tipo_documento is not None:
        raise ValidationError(
            {"tipo_documento": "Un ítem de acción se tilda a mano; no lleva tipo de documento."}
        )


@transaction.atomic
def agregar_item(
    *, actor, plantilla: PlantillaChecklist, etiqueta: str, tipo_item: str,
    tipo_documento=None, orden: int | None = None,
) -> ItemPlantilla:
    _validar_coherencia_item(tipo_item=tipo_item, tipo_documento=tipo_documento)
    if orden is None:
        # Al final de la lista: siguiente número después del mayor existente.
        ultimo = plantilla.items.order_by("-orden").values_list("orden", flat=True).first()
        orden = (ultimo or 0) + 1
    return ItemPlantilla.objects.create(
        creado_por=actor,
        plantilla=plantilla,
        etiqueta=etiqueta,
        tipo_item=tipo_item,
        tipo_documento=tipo_documento,
        orden=orden,
    )


@transaction.atomic
def actualizar_item(*, actor, item: ItemPlantilla, **datos) -> ItemPlantilla:
    """Edita un ítem de plantilla (etiqueta, orden, tipo, enlace, o baja lógica vía `activo`).

    No toca los procesos ya creados: son una foto (ItemProceso), por diseño. Se valida la
    coherencia tipo↔documento con el estado resultante, no solo con lo que vino en `datos`.
    """
    tipo_item = datos.get("tipo_item", item.tipo_item)
    tipo_documento = datos.get("tipo_documento", item.tipo_documento)
    _validar_coherencia_item(tipo_item=tipo_item, tipo_documento=tipo_documento)
    for campo, valor in datos.items():
        setattr(item, campo, valor)
    item.save()
    return item


# --- Avance de la tarjeta (ficha) ------------------------------------------------------

@transaction.atomic
def obtener_o_crear_proceso(*, actor, relacion, tipo_proceso: str) -> ProcesoEmpleado:
    """Devuelve el proceso de esa relación+tipo; lo crea perezosamente la primera vez.

    Al crearlo, fotografía los ítems ACTIVOS de la plantilla vigente de la empresa. Si no
    hay plantilla activa, el proceso nace sin ítems: la ficha muestra la tarjeta vacía con
    el aviso "no hay checklist configurado" (no bloquea el alta ni la baja).

    `get_or_create` cierra la carrera de dos primeras aperturas simultáneas: la segunda choca
    contra el único (relación, tipo) y recupera la ya creada en vez de duplicar.
    """
    proceso = ProcesoEmpleado.objects.filter(
        relacion_laboral=relacion, tipo_proceso=tipo_proceso
    ).first()
    if proceso is not None:
        return proceso

    plantilla = PlantillaChecklist.objects.filter(
        empresa=relacion.empresa, tipo_proceso=tipo_proceso, activa=True
    ).first()
    proceso, creado = ProcesoEmpleado.objects.get_or_create(
        relacion_laboral=relacion,
        tipo_proceso=tipo_proceso,
        defaults={"creado_por": actor, "plantilla": plantilla},
    )
    if creado and plantilla is not None:
        ItemProceso.objects.bulk_create(
            [
                ItemProceso(
                    creado_por=actor,
                    proceso=proceso,
                    item_plantilla=item,
                    orden=item.orden,
                    etiqueta=item.etiqueta,
                    tipo_item=item.tipo_item,
                    tipo_documento_id=item.tipo_documento_id,
                )
                for item in plantilla.items.filter(activo=True).order_by("orden", "id")
            ]
        )
    return proceso


@transaction.atomic
def tildar_item(*, actor, item: ItemProceso, hecho: bool) -> ItemProceso:
    """Tilda/destilda un ítem de ACCION, dejando constancia de quién y cuándo.

    Un ítem DOCUMENTAL se rechaza: su estado lo dicta el documento del legajo (una sola
    fuente de verdad), no un tilde manual que podría contradecirlo.
    """
    if item.tipo_item != TipoItem.ACCION:
        raise ValidationError(
            {"tipo_item": "Este ítem se completa cargando su documento en el legajo, no se tilda."}
        )
    item.completado = hecho
    if hecho:
        item.completado_por = actor
        item.completado_en = timezone.now()
    else:
        item.completado_por = None
        item.completado_en = None
    item.save(
        update_fields=["completado", "completado_por", "completado_en", "actualizado_en"]
    )
    return item
