"""Lectura de novedades: querysets scopeados por rol + cálculos de cadena (§6 bis, §7, §11).

Scoping por rol (igual que empleados): Admin/RRHH/Supervisor ven todo (el recorte fino
por sector del Supervisor se difiere a la fase de asistencias); el Empleado ve solo lo
propio. La vigencia efectiva de una cadena de prórrogas se calcula acá, nunca se guarda.
"""
from django.db.models import Q, QuerySet

from common import roles

from .models import EstadoNovedad, Novedad

_VERDADERO = {"1", "true", "si", "sí", "yes"}


def _puede_ver_todas(usuario) -> bool:
    return usuario.tiene_rol(roles.ADMIN, roles.RRHH, roles.SUPERVISOR)


def novedades_visibles_para(*, usuario, filtros=None, colapsar=False) -> QuerySet[Novedad]:
    qs = Novedad.objects.select_related(
        "empleado", "tipo_novedad", "relacion_laboral__empresa"
    ).prefetch_related("prorrogas")
    if not _puede_ver_todas(usuario):
        qs = qs.filter(empleado__usuario=usuario)  # solo lo propio
    filtros = filtros or {}
    expandir = str(filtros.get("expandir_cadenas", "")).lower() in _VERDADERO
    if colapsar and not expandir:
        # Cadenas colapsadas (§6 bis): la lista muestra la madre, no cada prórroga.
        qs = qs.filter(novedad_origen__isnull=True)
    return _aplicar_filtros(qs, filtros)


def _aplicar_filtros(qs: QuerySet[Novedad], filtros) -> QuerySet[Novedad]:
    empleado = filtros.get("empleado")
    tipo = filtros.get("tipo")  # codigo del catálogo
    estado = filtros.get("estado")
    empresa = filtros.get("empresa")
    desde = filtros.get("desde")
    hasta = filtros.get("hasta")
    busqueda = filtros.get("q")

    if empleado:
        qs = qs.filter(empleado_id=empleado)
    if tipo:
        qs = qs.filter(tipo_novedad__codigo=tipo)
    if estado:
        qs = qs.filter(estado=estado)
    if empresa:
        # `relacion_laboral` es opcional (p. ej. datos importados fuera del alta). Filtrar
        # solo por ella hacía desaparecer esas novedades de la lista: se caen del JOIN y no
        # aparecen bajo NINGUNA empresa. Igual que el ranking del dashboard, se cae a las
        # relaciones del empleado cuando la novedad no trae la suya.
        # distinct(): con relación en las dos empresas del grupo, el OR matchea dos veces.
        qs = qs.filter(
            Q(relacion_laboral__empresa_id=empresa)
            | Q(relacion_laboral__isnull=True, empleado__relaciones__empresa_id=empresa)
        ).distinct()
    if desde:
        qs = qs.filter(fecha_desde__gte=desde)
    if hasta:
        qs = qs.filter(fecha_desde__lte=hasta)
    if busqueda:
        qs = qs.filter(
            Q(motivo__icontains=busqueda)
            | Q(empleado__nombre__icontains=busqueda)
            | Q(empleado__apellido__icontains=busqueda)
            | Q(empleado__legajo__icontains=busqueda)
        )
    return qs


def novedad_madre(novedad: Novedad) -> Novedad:
    """Devuelve la madre de la cadena (la propia novedad si no es prórroga)."""
    return novedad.novedad_origen or novedad


def vigencia_efectiva(madre: Novedad) -> dict:
    """§6 bis: desde = fecha_desde de la madre; hasta = MAX(fecha_hasta) entre madre y
    prórrogas APROBADAS. `dias_totales` incluye ambos extremos. Todo calculado, nunca guardado.
    """
    hasta = madre.fecha_hasta
    for prorroga in madre.prorrogas.all():
        if prorroga.estado != EstadoNovedad.APROBADA or not prorroga.fecha_hasta:
            continue
        if hasta is None or prorroga.fecha_hasta > hasta:
            hasta = prorroga.fecha_hasta
    desde = madre.fecha_desde
    dias = (hasta - desde).days + 1 if (desde and hasta) else None
    return {"desde": desde, "hasta": hasta, "dias_totales": dias}


def cantidad_prorrogas(madre: Novedad) -> int:
    """Prórrogas vigentes (excluye las anuladas) — para el badge 'N prórrogas' del front."""
    return sum(1 for p in madre.prorrogas.all() if p.estado != EstadoNovedad.ANULADA)


def cadena_de(*, novedad: Novedad) -> dict:
    """Madre + prórrogas ordenadas cronológicamente + vigencia efectiva (§6 bis).

    Es lo que el front consume como línea de tiempo de la licencia.
    """
    madre = novedad_madre(novedad)
    prorrogas = list(madre.prorrogas.order_by("fecha_desde", "id"))
    vig = vigencia_efectiva(madre)
    return {
        "madre": madre,
        "prorrogas": prorrogas,
        "vigencia_efectiva": {"desde": vig["desde"], "hasta": vig["hasta"]},
        "dias_totales": vig["dias_totales"],
    }
