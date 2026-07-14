"""Métricas agregadas del panel general (dashboard).

Todo se calcula on-the-fly contra la base (nunca se guarda), igual que la vigencia
efectiva de novedades. Las definiciones de dominio están acordadas con el usuario y
se documentan acá para que el cálculo sea auditable:

- **Empleados activos**: personas con al menos una relación laboral vigente en la
  fecha (por fechas de ingreso/egreso, no por el campo `estado`, para poder mirar
  también el pasado y calcular la variación vs. el mes anterior).
- **Ingresos / egresos del mes**: relaciones con `fecha_ingreso` / `fecha_egreso`
  dentro del mes calendario.
- **Ausentismo del mes**: novedades madre (no prórrogas) de tipo FALTA,
  LICENCIA_MEDICA o ACCIDENTE con `fecha_desde` en el mes, excluyendo las anuladas
  y rechazadas.
- **Índice de rotación**: ((ingresos + egresos) / 2) ÷ dotación promedio × 100,
  con período mensual y anual (últimos 12 meses).
"""
from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Q

from apps.empleados.models import EstadoRelacion, RelacionLaboral
from apps.novedades.models import EstadoNovedad, Novedad

# Tipos que cuentan como ausentismo (acordado): ausencias no planificadas.
CODIGOS_AUSENTISMO = ("FALTA", "LICENCIA_MEDICA", "ACCIDENTE")
# Novedades fuera del workflow válido: no computan.
ESTADOS_NOVEDAD_EXCLUIDOS = (EstadoNovedad.ANULADA, EstadoNovedad.RECHAZADA)

_MESES_ABREV = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
_MESES_LARGO = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def _inicio_mes(d: date) -> date:
    return d.replace(day=1)


def _sumar_meses(inicio: date, meses: int) -> date:
    """Suma `meses` a un día-1 de mes y devuelve el día-1 resultante."""
    total = inicio.year * 12 + (inicio.month - 1) + meses
    return date(total // 12, total % 12 + 1, 1)


def _activos_ahora() -> int:
    """Empleados activos HOY según el campo `estado` (fuente de verdad, igual que la
    lista de empleados). Se usa para el KPI; una relación FINALIZADA nunca cuenta,
    aunque su `fecha_egreso` sea futura (baja con egreso diferido)."""
    return (
        RelacionLaboral.objects.filter(estado=EstadoRelacion.ACTIVA)
        .values("empleado_id")
        .distinct()
        .count()
    )


def _activos_a(fecha: date) -> int:
    """Empleados con al menos una relación vigente en `fecha` (por fechas):
    ingresó en/antes de `fecha` y (sin egreso o egresó después). Reconstrucción
    histórica para la variación y la dotación media de la rotación."""
    return (
        RelacionLaboral.objects.filter(fecha_ingreso__lte=fecha)
        .filter(Q(fecha_egreso__isnull=True) | Q(fecha_egreso__gt=fecha))
        .values("empleado_id")
        .distinct()
        .count()
    )


def _ingresos_en(desde: date, hasta: date) -> int:
    """Relaciones con fecha_ingreso en [desde, hasta)."""
    return RelacionLaboral.objects.filter(
        fecha_ingreso__gte=desde, fecha_ingreso__lt=hasta
    ).count()


def _egresos_en(desde: date, hasta: date) -> int:
    """Relaciones con fecha_egreso en [desde, hasta)."""
    return RelacionLaboral.objects.filter(
        fecha_egreso__gte=desde, fecha_egreso__lt=hasta
    ).count()


def _ausentismo_en(desde: date, hasta: date) -> int:
    """Novedades madre de ausentismo con fecha_desde en [desde, hasta)."""
    return (
        Novedad.objects.filter(
            novedad_origen__isnull=True,  # solo madres; no doble-contar prórrogas
            tipo_novedad__codigo__in=CODIGOS_AUSENTISMO,
            fecha_desde__gte=desde,
            fecha_desde__lt=hasta,
        )
        .exclude(estado__in=ESTADOS_NOVEDAD_EXCLUIDOS)
        .count()
    )


def _rotacion(ingresos: int, egresos: int, dotacion_promedio: float) -> float:
    """Índice de rotación estándar: media de altas y bajas sobre dotación media, en %."""
    if not dotacion_promedio:
        return 0.0
    return round(((ingresos + egresos) / 2) / dotacion_promedio * 100, 1)


def _rotacion_periodo(ini: date, fin: date, activos_fin: int) -> float:
    """Rotación de [ini, fin): promedio de dotación entre el día previo a `ini` y `fin`."""
    activos_ini = _activos_a(ini - timedelta(days=1))
    dot_prom = (activos_ini + activos_fin) / 2
    return _rotacion(_ingresos_en(ini, fin), _egresos_en(ini, fin), dot_prom)


def metricas_dashboard(*, hoy: date | None = None) -> dict:
    """Todas las métricas del panel, con variación vs. el mes anterior."""
    hoy = hoy or date.today()
    ini_mes = _inicio_mes(hoy)
    ini_mes_sig = _sumar_meses(ini_mes, 1)
    ini_mes_ant = _sumar_meses(ini_mes, -1)

    # --- KPIs (stock y flujo) ---
    activos_ahora = _activos_ahora()                        # valor del KPI (por estado)
    activos_hoy = _activos_a(hoy)                           # por fechas: dotación de la rotación
    activos_fin_mes_ant = _activos_a(ini_mes - timedelta(days=1))

    ingresos_mes = _ingresos_en(ini_mes, ini_mes_sig)
    ingresos_mes_ant = _ingresos_en(ini_mes_ant, ini_mes)
    egresos_mes = _egresos_en(ini_mes, ini_mes_sig)
    egresos_mes_ant = _egresos_en(ini_mes_ant, ini_mes)
    ausentismo_mes = _ausentismo_en(ini_mes, ini_mes_sig)
    ausentismo_mes_ant = _ausentismo_en(ini_mes_ant, ini_mes)

    # --- Rotación mensual / anual + serie de 12 meses para el gráfico ---
    rot_mensual = _rotacion_periodo(ini_mes, ini_mes_sig, activos_hoy)
    rot_mensual_ant = _rotacion_periodo(ini_mes_ant, ini_mes, activos_fin_mes_ant)

    ini_12m = _sumar_meses(ini_mes, -11)
    rot_anual = _rotacion_periodo(ini_12m, ini_mes_sig, activos_hoy)
    ini_12m_ant = _sumar_meses(ini_mes, -23)
    rot_anual_ant = _rotacion_periodo(ini_12m_ant, ini_12m, activos_fin_mes_ant)

    serie = []
    for i in range(11, -1, -1):
        m_ini = _sumar_meses(ini_mes, -i)
        m_fin = _sumar_meses(m_ini, 1)
        activos_m_fin = _activos_a(m_fin - timedelta(days=1))
        serie.append({
            "label": _MESES_ABREV[m_ini.month - 1],
            "valor": _rotacion_periodo(m_ini, m_fin, activos_m_fin),
        })

    # --- Ranking de faltas del mes (top 5), por EMPLEADO, medido en DÍAS ---
    # `total` = cantidad de DÍAS de falta (no cantidad de faltas): una falta que abarca
    # un rango cuenta todos sus días, ambos extremos inclusive. Se agrupa por empleado (no
    # por relación): una falta cuya relación quedó sin asociar (p. ej. datos importados
    # fuera del alta) no debe partir al empleado en dos filas ni perder la empresa. La
    # empresa se resuelve aparte, por su relación. La suma se hace en Python para tratar
    # bien las faltas abiertas (fecha_hasta null cuenta como 1 día).
    faltas = (
        Novedad.objects.filter(
            novedad_origen__isnull=True,
            tipo_novedad__codigo="FALTA",
            fecha_desde__gte=ini_mes,
            fecha_desde__lt=ini_mes_sig,
        )
        .exclude(estado__in=ESTADOS_NOVEDAD_EXCLUIDOS)
        .values("empleado_id", "empleado__nombre", "empleado__apellido", "fecha_desde", "fecha_hasta")
    )
    acc: dict[int, dict] = {}
    for f in faltas:
        fin = f["fecha_hasta"] or f["fecha_desde"]
        dias = (fin - f["fecha_desde"]).days + 1
        e = acc.setdefault(
            f["empleado_id"],
            {"nombre": f["empleado__nombre"], "apellido": f["empleado__apellido"], "dias": 0},
        )
        e["dias"] += dias
    # Top 5 por días (desc), desempate por apellido.
    top = sorted(acc.items(), key=lambda kv: (-kv[1]["dias"], kv[1]["apellido"]))[:5]
    # Empresa de cada empleado del ranking: la de su relación ACTIVA; si no tiene,
    # la de la más reciente. Evita el "—" cuando la falta no trae relación asociada.
    ids = [empleado_id for empleado_id, _ in top]
    empresa_por_empleado: dict[int, str] = {}
    for rel in (
        RelacionLaboral.objects.filter(empleado_id__in=ids)
        .select_related("empresa")
        .order_by("empleado_id", "estado", "-fecha_ingreso")  # ACTIVA < FINALIZADA, luego recencia
    ):
        empresa_por_empleado.setdefault(rel.empleado_id, rel.empresa.nombre)
    ranking_faltas = [
        {
            "nombre": f"{datos['nombre']} {datos['apellido']}".strip(),
            "empresa": empresa_por_empleado.get(empleado_id, "—"),
            "total": datos["dias"],
        }
        for empleado_id, datos in top
    ]

    return {
        "periodo": {
            "mes": ini_mes.isoformat(),
            "mes_label": f"{_MESES_LARGO[ini_mes.month - 1]} {ini_mes.year}",
        },
        "activos": {"valor": activos_ahora, "delta": activos_ahora - activos_fin_mes_ant},
        "ingresos_mes": {"valor": ingresos_mes, "delta": ingresos_mes - ingresos_mes_ant},
        "egresos_mes": {"valor": egresos_mes, "delta": egresos_mes - egresos_mes_ant},
        "ausentismo_mes": {"valor": ausentismo_mes, "delta": ausentismo_mes - ausentismo_mes_ant},
        "rotacion": {
            "mensual": {"valor": rot_mensual, "delta_pts": round(rot_mensual - rot_mensual_ant, 1)},
            "anual": {"valor": rot_anual, "delta_pts": round(rot_anual - rot_anual_ant, 1)},
            "serie": serie,
        },
        "ranking_faltas": ranking_faltas,
    }
