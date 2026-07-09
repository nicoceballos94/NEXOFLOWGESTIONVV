"""Lectura de empleados: querysets ya filtrados por scope del usuario (§7, §11).

Scoping por rol:
- Admin / RRHH / Supervisor: ven la dotación (el recorte fino por sector del
  Supervisor se implementa en la fase de asistencias, cuando exista el vínculo
  supervisor↔sector; hoy no hay dato que lo soporte).
- Empleado (o sin rol operativo): solo su propia ficha (scope forzado por objeto).
"""
from django.db.models import QuerySet

from common import roles

from .models import Empleado, RelacionLaboral


def _puede_ver_dotacion(usuario) -> bool:
    return usuario.tiene_rol(roles.ADMIN, roles.RRHH, roles.SUPERVISOR)


def empleados_visibles_para(*, usuario, filtros=None) -> QuerySet[Empleado]:
    qs = Empleado.objects.select_related("usuario").prefetch_related(
        "relaciones__empresa", "relaciones__sector", "relaciones__puesto"
    )
    if not _puede_ver_dotacion(usuario):
        qs = qs.filter(usuario=usuario)  # solo lo propio
    return _aplicar_filtros(qs, filtros or {})


def _aplicar_filtros(qs: QuerySet[Empleado], filtros) -> QuerySet[Empleado]:
    empresa = filtros.get("empresa")
    sector = filtros.get("sector")
    estado = filtros.get("estado")
    busqueda = filtros.get("q")

    if empresa:
        qs = qs.filter(relaciones__empresa_id=empresa)
    if sector:
        qs = qs.filter(relaciones__sector_id=sector)
    if estado:
        qs = qs.filter(relaciones__estado=estado)
    if busqueda:
        from django.db.models import Q

        qs = qs.filter(
            Q(nombre__icontains=busqueda)
            | Q(apellido__icontains=busqueda)
            | Q(legajo__icontains=busqueda)
            | Q(dni__icontains=busqueda)
        )
    # los filtros sobre `relaciones` (N por empleado) pueden duplicar filas.
    return qs.distinct()


def relaciones_de(*, empleado) -> QuerySet[RelacionLaboral]:
    return empleado.relaciones.select_related("empresa", "sector", "puesto")
