"""Alertas del día: lo que necesita atención hoy, en una tarjeta del panel (§11).

La tarjeta existía en el diseño con cuatro alertas inventadas (un cumpleaños de mentira, un
apto que vencía el 09/07) que no salían de ningún lado. Acá se arman con datos reales.

Es un **resumen accionable, no un listado**: se corta en MAX_ITEMS y la pantalla de Alertas
tiene la lista completa. Por eso se ordena por urgencia y no por fecha — lo que ya venció va
antes que un cumpleaños, siempre.

Tres orígenes, tres preguntas distintas:
- documentos y contratos vencidos o por vencer (reusa el selector de vencimientos),
- certificados que la novedad exige y nadie presentó,
- cumpleaños del día (el único que no es un problema: es para saludar).

Devuelve `estado` (bad/warn/info), no colores: el semáforo lo pinta el diseño.
"""
from __future__ import annotations

from datetime import date

from apps.empleados.models import Empleado, EstadoRelacion
from apps.novedades.models import EstadoNovedad, Novedad

from .vencimientos import vencimientos_de_la_dotacion

MAX_ITEMS = 6

# Una novedad rechazada nunca pasó y una anulada se borra de los hechos: su certificado no
# le falta a nadie.
ESTADOS_VIGENTES = [
    EstadoNovedad.REGISTRADA,
    EstadoNovedad.EN_PROCESO,
    EstadoNovedad.APROBADA,
    EstadoNovedad.CERRADA,
]

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def fecha_larga(hoy: date) -> str:
    """"Miércoles 15 de julio, 2026" — el subtítulo de la tarjeta, que estaba fijo."""
    return f"{DIAS[hoy.weekday()].capitalize()} {hoy.day} de {MESES[hoy.month - 1]}, {hoy.year}"


def _dmy(f: date) -> str:
    return f"{f.day:02d}/{f.month:02d}"


def _plural(n: int) -> str:
    return "s" if n != 1 else ""


def _texto_vencimiento(item: dict, hoy: date) -> str:
    """Cuántos días faltan o pasaron, en criollo. La fecha sola no dice qué tan urgente es."""
    if item["fecha"] is None:
        return f"{item['empleado']} — sin fecha de vencimiento cargada"
    dias = (item["fecha"] - hoy).days
    if dias < 0:
        cuando = f"venció hace {abs(dias)} día{_plural(abs(dias))}"
    elif dias == 0:
        cuando = "vence hoy"
    else:
        cuando = f"vence en {dias} día{_plural(dias)}"
    return f"{item['empleado']} — {cuando} ({_dmy(item['fecha'])})"


def _de_vencimientos(hoy: date) -> list[dict]:
    """Documentos y contratos vencidos o por vencer. Los que están al día no son alerta."""
    items = []
    for grupo in vencimientos_de_la_dotacion(hoy=hoy)["grupos"]:
        # El nombre del grupo ya es el rótulo ("Apto médico", "Contrato a plazo", …).
        etiqueta = grupo["tipo"]
        for i in grupo["items"]:
            if i["estado"] == "ok":
                continue
            # Sin fecha cargada no es "vencido" —no se sabe cuándo vence—: es documentación
            # incompleta. Sigue siendo alerta roja (estado bad), pero el rótulo dice la verdad.
            if i["estado"] == "bad":
                estado_txt = "sin fecha" if i["fecha"] is None else "vencido"
            else:
                estado_txt = "próximo a vencer"
            items.append(
                {
                    "title": f"{etiqueta} {estado_txt}",
                    "text": _texto_vencimiento(i, hoy),
                    "estado": i["estado"],
                    "_orden": i["fecha"] or date.min,
                }
            )
    return items


def _certificados_pendientes(hoy: date) -> list[dict]:
    """Novedades que exigen certificado y no lo tienen, ya empezadas.

    Antes de la fecha de inicio no falta nada: el certificado se presenta cuando el hecho
    ocurre, no antes.
    """
    novedades = (
        Novedad.objects.filter(
            tipo_novedad__requiere_certificado=True,
            certificado_recibido_en__isnull=True,
            fecha_desde__lte=hoy,
            estado__in=ESTADOS_VIGENTES,
            empleado__relaciones__estado=EstadoRelacion.ACTIVA,
        )
        .select_related("empleado", "tipo_novedad")
        .distinct()  # relación activa en las dos empresas del grupo → doble match del JOIN
    )
    return [
        {
            "title": "Certificado pendiente",
            "text": f"{n.empleado.nombre_natural} — {n.tipo_novedad.nombre.lower()} "
            f"{_dmy(n.fecha_desde)} sin certificado",
            "estado": "bad",
            "_orden": n.fecha_desde,
        }
        for n in novedades
    ]


def _cumpleanos(hoy: date) -> list[dict]:
    """Cumpleaños de hoy. `fecha_nacimiento` se carga desde siempre y no alimentaba nada.

    Se filtra por mes y día en la base (no en Python) para no traer la dotación entera.
    """
    nombres = [
        e.nombre_natural
        for e in Empleado.objects.filter(
            fecha_nacimiento__month=hoy.month,
            fecha_nacimiento__day=hoy.day,
            relaciones__estado=EstadoRelacion.ACTIVA,
        )
        .distinct()
        .order_by("apellido", "nombre")
    ]
    if not nombres:
        return []
    texto = (
        f"{nombres[0]} cumple años hoy"
        if len(nombres) == 1
        # No se listan ocho nombres en una tarjeta de resumen.
        else f"{nombres[0]} y {len(nombres) - 1} más cumplen años hoy"
    )
    return [{"title": "Cumpleaños del día", "text": texto, "estado": "info", "_orden": date.min}]


def alertas_del_dia(*, hoy: date | None = None) -> dict:
    """Las alertas de hoy, ya ordenadas y recortadas para la tarjeta del panel."""
    hoy = hoy or date.today()
    items = _de_vencimientos(hoy) + _certificados_pendientes(hoy) + _cumpleanos(hoy)

    # Vencido antes que por vencer antes que cumpleaños; dentro de cada grupo, lo más viejo
    # primero. `total` se cuenta ANTES de recortar: la tarjeta mentiría si mostrara 6 de 20
    # sin decirlo.
    prioridad = {"bad": 0, "warn": 1, "info": 2}
    items.sort(key=lambda i: (prioridad[i["estado"]], i["_orden"]))
    return {
        "fecha": fecha_larga(hoy),
        "total": len(items),
        "items": [
            {"title": i["title"], "text": i["text"], "estado": i["estado"]}
            for i in items[:MAX_ITEMS]
        ],
    }
