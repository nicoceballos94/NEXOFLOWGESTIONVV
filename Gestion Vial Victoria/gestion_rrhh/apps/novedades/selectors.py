"""Lectura de novedades: querysets scopeados por rol + cálculos de cadena (§6 bis, §7, §11).

Scoping por rol (igual que empleados): Admin/RRHH/Supervisor ven todo (el recorte fino
por sector del Supervisor se difiere a la fase de asistencias); el Empleado ve solo lo
propio. La vigencia efectiva de una cadena de prórrogas se calcula acá, nunca se guarda.
"""
from django.db.models import Q, QuerySet
from django.utils.dateparse import parse_date
from rest_framework.exceptions import ValidationError

from common import roles

from .models import EstadoNovedad, Novedad
from .periodos import cadena_intersecta_desde

_VERDADERO = {"1", "true", "si", "sí", "yes"}


def novedades_visibles_para(*, usuario, filtros=None, colapsar=False) -> QuerySet[Novedad]:
    qs = Novedad.objects.select_related(
        "empleado", "tipo_novedad", "relacion_laboral__empresa"
    ).prefetch_related("prorrogas")
    supervisor_restringido = usuario.tiene_rol(
        roles.SUPERVISOR
    ) and not usuario.tiene_rol(
        roles.ADMIN, roles.RRHH
    )
    if supervisor_restringido:
        qs = qs.filter(
            Q(
                relacion_laboral__estado="ACTIVA",
                relacion_laboral__supervisor=usuario,
            )
            | Q(empleado__usuario=usuario)
        )
    elif not usuario.tiene_rol(roles.ADMIN, roles.RRHH):
        qs = qs.filter(empleado__usuario=usuario)  # solo lo propio
    filtros = filtros or {}
    expandir = str(filtros.get("expandir_cadenas", "")).lower() in _VERDADERO
    if colapsar and not expandir:
        # Cadenas colapsadas (§6 bis): la lista muestra la madre, no cada prórroga.
        qs = qs.filter(novedad_origen__isnull=True)
    return _aplicar_filtros(
        qs,
        filtros,
        incluir_motivo=not supervisor_restringido,
    )


def _aplicar_filtros(
    qs: QuerySet[Novedad],
    filtros,
    *,
    incluir_motivo: bool = True,
) -> QuerySet[Novedad]:
    empleado = filtros.get("empleado")
    tipo = filtros.get("tipo")  # codigo del catálogo
    estado = filtros.get("estado")
    empresa = filtros.get("empresa")
    desde = filtros.get("desde")
    hasta = filtros.get("hasta")
    busqueda = filtros.get("q")

    if empleado:
        qs = qs.filter(empleado_id=_entero_positivo(empleado, "empleado"))
    if tipo:
        qs = qs.filter(tipo_novedad__codigo=tipo)
    if estado:
        estados_validos = {valor for valor, _ in EstadoNovedad.choices}
        if estado not in estados_validos:
            raise ValidationError({"estado": "Estado de novedad inválido."})
        qs = qs.filter(estado=estado)
    if empresa:
        qs = qs.filter(
            relacion_laboral__empresa_id=_entero_positivo(empresa, "empresa")
        )
    if desde:
        desde = _fecha(desde, "desde")
        qs = qs.filter(cadena_intersecta_desde(desde)).distinct()
    if hasta:
        qs = qs.filter(fecha_desde__lte=_fecha(hasta, "hasta"))
    if busqueda:
        criterio = (
            Q(empleado__nombre__icontains=busqueda)
            | Q(empleado__apellido__icontains=busqueda)
            | Q(empleado__legajo__icontains=busqueda)
        )
        if incluir_motivo:
            criterio |= Q(motivo__icontains=busqueda)
        qs = qs.filter(criterio)
    return qs


def _entero_positivo(valor, campo: str) -> int:
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ValidationError({campo: "Debe ser un identificador numérico."})
    if numero <= 0:
        raise ValidationError({campo: "Debe ser un identificador positivo."})
    return numero


def _fecha(valor, campo: str):
    fecha = parse_date(str(valor))
    if fecha is None:
        raise ValidationError({campo: "Debe tener formato AAAA-MM-DD y ser una fecha válida."})
    return fecha


def novedad_madre(novedad: Novedad) -> Novedad:
    """Devuelve la madre de la cadena (la propia novedad si no es prórroga)."""
    return novedad.novedad_origen or novedad


def vigencia_efectiva(madre: Novedad) -> dict:
    """§6 bis: desde = fecha_desde de la madre; hasta = MAX(fecha_hasta) entre madre y
    prórrogas APROBADAS o CERRADAS. `dias_totales` incluye ambos extremos. Todo calculado,
    nunca guardado.
    """
    hasta = madre.fecha_hasta
    for prorroga in madre.prorrogas.all():
        if prorroga.estado not in (
            EstadoNovedad.APROBADA,
            EstadoNovedad.CERRADA,
        ) or not prorroga.fecha_hasta:
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
