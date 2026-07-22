"""Métricas de la pantalla Reportes: dotación en el tiempo, ausentismo por tipo y
motivos de egreso.

Todo se calcula on-the-fly contra la base (nunca se guarda), igual que el panel. Las
definiciones están acordadas con el usuario y se documentan acá para que el cálculo sea
auditable:

- **Dotación en el tiempo**: empleados con al menos una relación vigente por fechas a fin
  de cada uno de los últimos 12 meses (misma reconstrucción histórica que la dotación
  media de la rotación). El número grande es la dotación ACTUAL por `estado` —la misma
  fuente de verdad que el KPI del panel y la lista de empleados—, y la variación es el
  cambio porcentual respecto de la dotación de hace 12 meses.
- **Ausentismo por tipo** (año calendario en curso): novedades madre (no prórrogas) con
  `fecha_desde` en el año, de tipos que OCUPAN el período del empleado (faltas, licencias,
  accidentes, vacaciones, permisos: los eventos que lo sacan del calendario), excluyendo
  anuladas y rechazadas, contadas como eventos y agrupadas por tipo. Es la distribución de
  por qué la gente no estuvo.
- **Motivos de egreso** (últimos 12 meses): relaciones con `fecha_egreso` en los últimos
  365 días, agrupadas por `motivo_egreso`.

Reusa `_Dotacion` y los helpers de fecha del panel (`selectors`): la dotación histórica es
exactamente la misma cuenta, no tiene sentido tener dos definiciones que puedan divergir.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Count

from apps.empleados.models import MotivoEgreso, RelacionLaboral
from apps.novedades.models import Novedad

from .selectors import (
    _MESES_ABREV,
    ESTADOS_NOVEDAD_EXCLUIDOS,
    _Dotacion,
    _inicio_mes,
    _sumar_meses,
)


def _pct(parte: int, total: int) -> int:
    """Porcentaje entero de `parte` sobre `total` (0 si no hay total)."""
    return round(parte / total * 100) if total else 0


def _dotacion_en_el_tiempo(dotacion: _Dotacion, ini_mes: date) -> dict:
    """Serie de dotación (por fechas) a fin de cada uno de los últimos 12 meses, más el
    total actual (por estado) y la variación % contra la dotación de hace 12 meses."""
    serie = []
    for i in range(11, -1, -1):
        m_ini = _sumar_meses(ini_mes, -i)
        fin_mes = _sumar_meses(m_ini, 1) - timedelta(days=1)
        serie.append({
            "label": _MESES_ABREV[m_ini.month - 1],
            "valor": dotacion.activos_a(fin_mes),
        })

    total = dotacion.activos_ahora()
    # Línea de base: la dotación el día previo al primer mes de la serie (hace 12 meses).
    base = dotacion.activos_a(_sumar_meses(ini_mes, -11) - timedelta(days=1))
    delta_pct = round((total - base) / base * 100, 1) if base else 0.0
    return {"total": total, "delta_pct": delta_pct, "serie": serie}


def _ausentismo_por_tipo(ini_anio: date, ini_anio_sig: date) -> dict:
    """Distribución de eventos de ausentismo del año, por tipo de novedad."""
    filas = (
        Novedad.objects.filter(
            novedad_origen__isnull=True,             # solo madres; no doble-contar prórrogas
            tipo_novedad__ocupa_periodo=True,        # las que sacan al empleado del calendario
            fecha_desde__gte=ini_anio,
            fecha_desde__lt=ini_anio_sig,
        )
        .exclude(estado__in=ESTADOS_NOVEDAD_EXCLUIDOS)
        .values("tipo_novedad__nombre")
        .annotate(cantidad=Count("id"))
        .order_by("-cantidad", "tipo_novedad__nombre")
    )
    total = sum(f["cantidad"] for f in filas)
    items = [
        {"label": f["tipo_novedad__nombre"], "cantidad": f["cantidad"],
         "pct": _pct(f["cantidad"], total)}
        for f in filas
    ]
    return {"anio": ini_anio.year, "total": total, "items": items}


def _motivos_de_egreso(hoy: date) -> dict:
    """Distribución de bajas de los últimos 12 meses, por motivo de egreso."""
    desde = hoy - timedelta(days=365)
    filas = (
        RelacionLaboral.objects.filter(fecha_egreso__gte=desde, fecha_egreso__lte=hoy)
        .values("motivo_egreso")
        .annotate(cantidad=Count("id"))
        .order_by("-cantidad", "motivo_egreso")
    )
    total = sum(f["cantidad"] for f in filas)
    etiquetas = dict(MotivoEgreso.choices)
    items = [
        {
            # motivo vacío (baja histórica sin motivo cargado) no puede quedar sin etiqueta.
            "label": etiquetas.get(f["motivo_egreso"], "") or "Sin especificar",
            "cantidad": f["cantidad"],
            "pct": _pct(f["cantidad"], total),
        }
        for f in filas
    ]
    return {"total": total, "items": items}


def metricas_reportes(*, hoy: date | None = None) -> dict:
    """Las tres métricas de la pantalla Reportes."""
    hoy = hoy or date.today()
    ini_mes = _inicio_mes(hoy)
    ini_anio = date(hoy.year, 1, 1)
    ini_anio_sig = date(hoy.year + 1, 1, 1)

    dotacion = _Dotacion.leer()  # única lectura de relaciones; el resto se cuenta en memoria
    return {
        "dotacion": _dotacion_en_el_tiempo(dotacion, ini_mes),
        "ausentismo": _ausentismo_por_tipo(ini_anio, ini_anio_sig),
        "egresos": _motivos_de_egreso(hoy),
    }
