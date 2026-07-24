"""Lectura de empleados: querysets ya filtrados por scope del usuario (§7, §11).

Scoping por rol:
- Admin / RRHH: ven toda la dotación.
- Supervisor: únicamente personas cuya relación ACTIVA está asignada a ese usuario.
- Empleado (o sin rol operativo): solo su propia ficha (scope forzado por objeto).
"""
from django.db.models import Q, QuerySet

from common import roles
from common.queryparams import entero_positivo

from .models import Empleado, EstadoRelacion, RelacionLaboral


def _es_rrhh_o_admin(usuario) -> bool:
    return usuario.tiene_rol(roles.ADMIN, roles.RRHH)


def empleados_visibles_para(*, usuario, filtros=None) -> QuerySet[Empleado]:
    filtros = filtros or {}
    qs = Empleado.objects.select_related("usuario").prefetch_related(
        "relaciones__empresa",
        "relaciones__sector",
        "relaciones__puesto",
        "relaciones__supervisor",
    )
    if _es_rrhh_o_admin(usuario):
        return _aplicar_filtros(qs, filtros, incluir_dni=True)
    if usuario.tiene_rol(roles.SUPERVISOR):
        # El scope del equipo y empresa/sector/estado deben compartir el MISMO alias
        # SQL. Si se aplican en dos .filter(), una relación histórica ajena puede
        # satisfacer el filtro y revelar su existencia aunque la activa sea otra.
        equipo = _aplicar_filtros_equipo(
            qs,
            usuario=usuario,
            filtros=filtros,
        )
        propia = _aplicar_filtros(
            qs.filter(usuario=usuario),
            filtros,
            incluir_dni=False,
        )
        return qs.filter(
            Q(pk__in=equipo.values("pk")) | Q(pk__in=propia.values("pk"))
        ).distinct()
    return _aplicar_filtros(
        qs.filter(usuario=usuario),
        filtros,
        incluir_dni=False,
    )


def _criterio_busqueda(busqueda, *, incluir_dni: bool):
    criterio = (
        Q(nombre__icontains=busqueda)
        | Q(apellido__icontains=busqueda)
        | Q(legajo__icontains=busqueda)
    )
    if incluir_dni:
        criterio |= Q(dni__icontains=busqueda)
    return criterio


def _aplicar_filtros_equipo(
    qs: QuerySet[Empleado],
    *,
    usuario,
    filtros,
) -> QuerySet[Empleado]:
    """Filtra exclusivamente la asignación activa del Supervisor."""

    estado = filtros.get("estado")
    if estado and estado != EstadoRelacion.ACTIVA:
        return qs.none()

    relacion = {
        "relaciones__estado": EstadoRelacion.ACTIVA,
        "relaciones__supervisor": usuario,
    }
    empresa = filtros.get("empresa")
    sector = filtros.get("sector")
    if empresa:
        relacion["relaciones__empresa_id"] = entero_positivo(empresa, "empresa")
    if sector:
        relacion["relaciones__sector_id"] = entero_positivo(sector, "sector")

    qs = qs.filter(**relacion)
    busqueda = filtros.get("q")
    if busqueda:
        # Nunca se habilita DNI para el equipo: sería un oracle aunque el campo no salga.
        qs = qs.filter(_criterio_busqueda(busqueda, incluir_dni=False))
    return qs.distinct()


def _aplicar_filtros(
    qs: QuerySet[Empleado],
    filtros,
    *,
    incluir_dni: bool,
) -> QuerySet[Empleado]:
    empresa = filtros.get("empresa")
    sector = filtros.get("sector")
    estado = filtros.get("estado")
    busqueda = filtros.get("q")

    # empresa/sector/estado describen la MISMA relación laboral, así que van en un solo
    # .filter(): cada llamada separada genera su propio JOIN y las condiciones podrían
    # satisfacerse con relaciones distintas (activo en la empresa A + finalizado en la B
    # matchearía "empresa=B & estado=ACTIVA").
    de_la_relacion = {}
    if empresa:
        de_la_relacion["relaciones__empresa_id"] = entero_positivo(empresa, "empresa")
    if sector:
        de_la_relacion["relaciones__sector_id"] = entero_positivo(sector, "sector")
    if estado:
        de_la_relacion["relaciones__estado"] = estado
    if de_la_relacion:
        qs = qs.filter(**de_la_relacion)
    if busqueda:
        qs = qs.filter(_criterio_busqueda(busqueda, incluir_dni=incluir_dni))
    # los filtros sobre `relaciones` (N por empleado) pueden duplicar filas.
    return qs.distinct()


def relaciones_de(*, empleado) -> QuerySet[RelacionLaboral]:
    return empleado.relaciones.select_related("empresa", "sector", "puesto", "supervisor")
