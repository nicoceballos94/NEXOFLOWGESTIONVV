"""Lectura de onboarding/offboarding: arma la tarjeta con el estado en vivo de cada ítem.

El estado de un ítem DOCUMENTAL se calcula acá — ¿existe el documento del legajo de ese
tipo con archivo adjunto? — y nunca se guarda: una sola fuente de verdad (el documento). La
compleción del proceso y el "cuándo se completó" se derivan de los ítems, sin campo que se
pueda desincronizar.

Lee `DocumentoEmpleado` (app empleados) para el cálculo del ítem documental. Es una lectura
cruzada por FK; la escritura de documentos sigue siendo de `empleados` (regla §10).
"""
from django.db.models import QuerySet

from apps.empleados.models import DocumentoEmpleado

from .models import PlantillaChecklist, ProcesoEmpleado, TipoItem


def plantillas_visibles(*, filtros=None) -> QuerySet[PlantillaChecklist]:
    """Plantillas para el ABM de Configuración, con sus ítems ordenados."""
    qs = PlantillaChecklist.objects.select_related("empresa").prefetch_related(
        "items__tipo_documento"
    )
    filtros = filtros or {}
    empresa = filtros.get("empresa")
    tipo_proceso = filtros.get("tipo_proceso")
    activa = filtros.get("activa")
    if empresa:
        qs = qs.filter(empresa_id=empresa)
    if tipo_proceso:
        qs = qs.filter(tipo_proceso=tipo_proceso)
    if activa is not None:
        qs = qs.filter(activa=activa)
    return qs


def _momentos_docs_completos(empleado) -> dict[int, object]:
    """{tipo_documento_id: creado_en} de los documentos del empleado que tienen archivo.

    Una sola query resuelve el estado de todos los ítems documentales de la tarjeta (evita el
    N+1 de preguntar por cada ítem). El UNIQUE (empleado, tipo_documento) garantiza uno por
    tipo; si hubiera más, queda el último iterado.
    """
    momentos: dict[int, object] = {}
    for tipo_id, creado_en in (
        DocumentoEmpleado.objects.filter(empleado=empleado)
        .exclude(archivo="")
        .values_list("tipo_documento_id", "creado_en")
    ):
        momentos[tipo_id] = creado_en
    return momentos


def armar_tarjeta(*, proceso: ProcesoEmpleado) -> dict:
    """Datos de la tarjeta de la ficha: ítems con estado en vivo, progreso y compleción.

    `sin_plantilla=True` (proceso sin ítems) es la señal para que la ficha muestre el aviso
    "no hay checklist configurado para esta empresa".
    """
    empleado = proceso.relacion_laboral.empleado
    momentos_docs = _momentos_docs_completos(empleado)

    items = []
    momentos_hechos = []
    for item in proceso.items.all():
        if item.tipo_item == TipoItem.DOCUMENTAL:
            momento = momentos_docs.get(item.tipo_documento_id)
            hecho = momento is not None
            completado_por = None
        else:
            hecho = item.completado
            momento = item.completado_en if hecho else None
            completado_por = item.completado_por_id if hecho else None
        if hecho and momento is not None:
            momentos_hechos.append(momento)
        items.append(
            {
                "id": item.id,
                "orden": item.orden,
                "etiqueta": item.etiqueta,
                "tipo_item": item.tipo_item,
                "tipo_documento": item.tipo_documento_id,
                "hecho": hecho,
                "completado_en": momento,
                "completado_por": completado_por,
            }
        )

    total = len(items)
    hechos = sum(1 for i in items if i["hecho"])
    completo = total > 0 and hechos == total
    return {
        "id": proceso.id,
        "tipo_proceso": proceso.tipo_proceso,
        "sin_plantilla": total == 0,
        "progreso": {
            "hechos": hechos,
            "total": total,
            "porcentaje": round(hechos * 100 / total) if total else 0,
        },
        "completo": completo,
        # Derivado: el más tardío de los momentos, solo cuando está todo hecho.
        "completado_en": max(momentos_hechos) if completo and momentos_hechos else None,
        "items": items,
    }
