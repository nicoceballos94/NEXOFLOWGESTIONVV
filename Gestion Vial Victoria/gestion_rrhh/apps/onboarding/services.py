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
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import Accion, registrar_evento, tomar_foto
from apps.empleados.models import Empleado, EstadoRelacion, RelacionLaboral, TipoDocumento
from apps.organizacion.models import Empresa

from .models import (
    EstadoPlantilla,
    ItemPlantilla,
    ItemProceso,
    PlantillaChecklist,
    ProcesoEmpleado,
    TipoItem,
    TipoProceso,
)

# --- ABM de plantillas (Configuración) -------------------------------------------------


def _bloquear_empresa(empresa_id: int) -> None:
    """Serializa cambios de versiones del mismo alcance sin locks sobre filas inexistentes."""
    Empresa.objects.select_for_update().only("id").get(pk=empresa_id)


@transaction.atomic
def crear_plantilla(
    *, actor, empresa, tipo_proceso: str, sector=None
) -> PlantillaChecklist:
    """Crea un borrador nuevo y copia los ítems vigentes de la versión publicada."""
    _bloquear_empresa(empresa.pk)
    alcance = PlantillaChecklist.objects.filter(
        empresa=empresa,
        sector=sector,
        tipo_proceso=tipo_proceso,
    )
    borrador = alcance.filter(estado=EstadoPlantilla.BORRADOR).first()
    if borrador is not None:
        return borrador
    version = (alcance.aggregate(maxima=Max("version"))["maxima"] or 0) + 1
    publicada = alcance.filter(estado=EstadoPlantilla.PUBLICADA).first()
    plantilla = PlantillaChecklist.objects.create(
        creado_por=actor,
        empresa=empresa,
        sector=sector,
        tipo_proceso=tipo_proceso,
        version=version,
        estado=EstadoPlantilla.BORRADOR,
    )
    if publicada is not None:
        ItemPlantilla.objects.bulk_create(
            [
                ItemPlantilla(
                    creado_por=actor,
                    plantilla=plantilla,
                    orden=item.orden,
                    etiqueta=item.etiqueta,
                    tipo_item=item.tipo_item,
                    tipo_documento_id=item.tipo_documento_id,
                    activo=True,
                )
                for item in publicada.items.filter(activo=True).order_by("orden", "id")
            ]
        )
    registrar_evento(actor=actor, accion=Accion.PLANTILLA_CREADA, objeto=plantilla)
    return plantilla


@transaction.atomic
def publicar_plantilla(*, actor, plantilla: PlantillaChecklist) -> PlantillaChecklist:
    _bloquear_empresa(plantilla.empresa_id)
    plantilla = PlantillaChecklist.objects.select_for_update().get(pk=plantilla.pk)
    if plantilla.estado != EstadoPlantilla.BORRADOR:
        raise ValidationError({"estado": "Solo se puede publicar una plantilla en borrador."})

    tipos_requeridos = set(
        plantilla.items.filter(
            activo=True,
            tipo_item=TipoItem.DOCUMENTAL,
        ).values_list("tipo_documento_id", flat=True)
    )
    tipos_activos = set(
        TipoDocumento.objects.select_for_update()
        .filter(pk__in=tipos_requeridos, activo=True)
        .values_list("pk", flat=True)
    )
    if tipos_activos != tipos_requeridos:
        raise ValidationError(
            {
                "items": (
                    "La plantilla contiene un tipo de documento inactivo. "
                    "Quitalo o reemplazalo antes de publicar."
                )
            }
        )

    anteriores = PlantillaChecklist.objects.select_for_update().filter(
        empresa=plantilla.empresa,
        sector=plantilla.sector,
        tipo_proceso=plantilla.tipo_proceso,
        estado=EstadoPlantilla.PUBLICADA,
    )
    for anterior in anteriores:
        antes = tomar_foto(anterior, campos=("estado",))
        anterior.estado = EstadoPlantilla.ARCHIVADA
        anterior.save(update_fields=["estado", "actualizado_en"])
        registrar_evento(
            actor=actor,
            accion=Accion.PLANTILLA_ARCHIVADA,
            objeto=anterior,
            antes=antes,
            campos=("estado",),
        )

    antes = tomar_foto(plantilla, campos=("estado",))
    plantilla.estado = EstadoPlantilla.PUBLICADA
    plantilla.save(update_fields=["estado", "actualizado_en"])
    registrar_evento(
        actor=actor,
        accion=Accion.PLANTILLA_PUBLICADA,
        objeto=plantilla,
        antes=antes,
        campos=("estado",),
    )
    return plantilla


@transaction.atomic
def archivar_plantilla(*, actor, plantilla: PlantillaChecklist) -> PlantillaChecklist:
    _bloquear_empresa(plantilla.empresa_id)
    plantilla = PlantillaChecklist.objects.select_for_update().get(pk=plantilla.pk)
    if plantilla.estado == EstadoPlantilla.ARCHIVADA:
        return plantilla
    antes = tomar_foto(plantilla, campos=("estado",))
    plantilla.estado = EstadoPlantilla.ARCHIVADA
    plantilla.save(update_fields=["estado", "actualizado_en"])
    registrar_evento(
        actor=actor,
        accion=Accion.PLANTILLA_ARCHIVADA,
        objeto=plantilla,
        antes=antes,
        campos=("estado",),
    )
    return plantilla


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


def _bloquear_tipo_documento_activo(tipo_documento):
    if tipo_documento is None:
        return None
    bloqueado = TipoDocumento.objects.select_for_update().get(pk=tipo_documento.pk)
    if not bloqueado.activo:
        raise ValidationError(
            {"tipo_documento": "El tipo de documento seleccionado está inactivo."}
        )
    return bloqueado


@transaction.atomic
def agregar_item(
    *, actor, plantilla: PlantillaChecklist, etiqueta: str, tipo_item: str,
    tipo_documento=None, orden: int | None = None,
) -> ItemPlantilla:
    plantilla = PlantillaChecklist.objects.select_for_update().get(pk=plantilla.pk)
    if plantilla.estado != EstadoPlantilla.BORRADOR:
        raise ValidationError({"estado": "Los ítems solo se editan en una versión borrador."})
    tipo_documento = _bloquear_tipo_documento_activo(tipo_documento)
    _validar_coherencia_item(tipo_item=tipo_item, tipo_documento=tipo_documento)
    if orden is None:
        # Al final de la lista: siguiente número después del mayor existente.
        ultimo = plantilla.items.order_by("-orden").values_list("orden", flat=True).first()
        orden = (ultimo or 0) + 1
    item = ItemPlantilla.objects.create(
        creado_por=actor,
        plantilla=plantilla,
        etiqueta=etiqueta,
        tipo_item=tipo_item,
        tipo_documento=tipo_documento,
        orden=orden,
    )
    registrar_evento(actor=actor, accion=Accion.PLANTILLA_ITEM_CREADO, objeto=item)
    return item


@transaction.atomic
def actualizar_item(*, actor, item: ItemPlantilla, **datos) -> ItemPlantilla:
    """Edita un ítem de plantilla (etiqueta, orden, tipo, enlace, o baja lógica vía `activo`).

    No toca los procesos ya creados: son una foto (ItemProceso), por diseño. Se valida la
    coherencia tipo↔documento con el estado resultante, no solo con lo que vino en `datos`.
    """
    item = ItemPlantilla.objects.select_for_update().select_related("plantilla").get(pk=item.pk)
    if item.plantilla.estado != EstadoPlantilla.BORRADOR:
        raise ValidationError({"estado": "Los ítems solo se editan en una versión borrador."})
    tipo_item = datos.get("tipo_item", item.tipo_item)
    tipo_documento = datos.get("tipo_documento", item.tipo_documento)
    tipo_documento = _bloquear_tipo_documento_activo(tipo_documento)
    if "tipo_documento" in datos:
        datos["tipo_documento"] = tipo_documento
    _validar_coherencia_item(tipo_item=tipo_item, tipo_documento=tipo_documento)
    antes = tomar_foto(item)
    for campo, valor in datos.items():
        setattr(item, campo, valor)
    item.save()
    registrar_evento(
        actor=actor,
        accion=Accion.PLANTILLA_ITEM_ACTUALIZADO,
        objeto=item,
        antes=antes,
        solo_si_cambia=True,
    )
    return item


# --- Avance de la tarjeta (ficha) ------------------------------------------------------

@transaction.atomic
def iniciar_proceso(*, actor, relacion, tipo_proceso: str) -> ProcesoEmpleado:
    """Inicia explícitamente el proceso y fotografía la versión publicada.

    Al crearlo, fotografía los ítems ACTIVOS de la plantilla vigente de la empresa. Si no
    hay plantilla activa, el proceso nace sin ítems: la ficha muestra la tarjeta vacía con
    el aviso "no hay checklist configurado" (no bloquea el alta ni la baja).

    `get_or_create` cierra la carrera de dos primeras aperturas simultáneas: la segunda choca
    contra el único (relación, tipo) y recupera la ya creada en vez de duplicar.
    """
    # Orden canónico de todo flujo laboral: persona → relación. Además de serializar una
    # baja concurrente, evita el ciclo relación → auditoría(FK empleado) contra
    # finalizar_relacion(), que bloquea primero al empleado y luego a la relación.
    Empleado.objects.select_for_update().only("id").get(pk=relacion.empleado_id)
    relacion = (
        RelacionLaboral.objects.select_for_update(of=("self",))
        .select_related("empresa", "sector", "empleado")
        .get(pk=relacion.pk)
    )
    if tipo_proceso == TipoProceso.INGRESO and relacion.estado != EstadoRelacion.ACTIVA:
        raise ValidationError(
            {"tipo_proceso": "El onboarding requiere una relación activa."}
        )
    if tipo_proceso == TipoProceso.EGRESO and relacion.estado != EstadoRelacion.FINALIZADA:
        raise ValidationError(
            {"tipo_proceso": "El offboarding requiere una relación finalizada."}
        )
    if tipo_proceso not in {TipoProceso.INGRESO, TipoProceso.EGRESO}:
        raise ValidationError({"tipo_proceso": "Tipo de proceso inválido."})

    proceso = ProcesoEmpleado.objects.filter(
        relacion_laboral=relacion, tipo_proceso=tipo_proceso
    ).first()
    if proceso is not None:
        return proceso

    plantilla = (
        PlantillaChecklist.objects.filter(
            empresa=relacion.empresa,
            sector=relacion.sector,
            tipo_proceso=tipo_proceso,
            estado=EstadoPlantilla.PUBLICADA,
        ).first()
        or PlantillaChecklist.objects.filter(
            empresa=relacion.empresa,
            sector__isnull=True,
            tipo_proceso=tipo_proceso,
            estado=EstadoPlantilla.PUBLICADA,
        ).first()
    )
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
    if creado:
        registrar_evento(
            actor=actor,
            accion=Accion.CHECKLIST_INICIADO,
            objeto=proceso,
        )
    return proceso


# Alias temporal para llamadas internas antiguas. Las vistas GET ya no lo invocan.
obtener_o_crear_proceso = iniciar_proceso


@transaction.atomic
def tildar_item(*, actor, item: ItemProceso, hecho: bool) -> ItemProceso:
    """Tilda/destilda un ítem de ACCION, dejando constancia de quién y cuándo.

    Un ítem DOCUMENTAL se rechaza: su estado lo dicta el documento del legajo (una sola
    fuente de verdad), no un tilde manual que podría contradecirlo.
    """
    item = ItemProceso.objects.select_for_update().select_related(
        "proceso__relacion_laboral__empleado"
    ).get(pk=item.pk)
    if item.tipo_item != TipoItem.ACCION:
        raise ValidationError(
            {"tipo_item": "Este ítem se completa cargando su documento en el legajo, no se tilda."}
        )
    antes = tomar_foto(item, campos=("completado",))
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
    # Destildar es lo que importa auditar: el ítem guarda la constancia de quién lo tildó
    # (`completado_por`), pero al destildarlo esa constancia SE BORRA. Sin la bitácora, un
    # ítem revertido no deja ni rastro de que alguna vez estuvo hecho, ni de quién lo revirtió.
    # `campos` acota el diff a `completado`: el quién/cuándo ya son el autor y el momento del
    # propio evento, repetirlos en el diff sería decir dos veces lo mismo.
    registrar_evento(
        actor=actor,
        accion=Accion.CHECKLIST_ITEM_COMPLETADO if hecho else Accion.CHECKLIST_ITEM_REVERTIDO,
        objeto=item,
        antes=antes,
        campos=("completado",),
        solo_si_cambia=True,  # volver a tildar lo ya tildado no es un hecho nuevo
    )
    return item
