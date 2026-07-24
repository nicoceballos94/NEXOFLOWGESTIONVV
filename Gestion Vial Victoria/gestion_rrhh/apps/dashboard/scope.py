"""Alcance de datos agregados: global para RRHH/Admin, equipo propio para Supervisor."""

from common import roles


def supervisor_restringido(usuario) -> bool:
    return bool(
        usuario
        and usuario.is_authenticated
        and usuario.tiene_rol(roles.SUPERVISOR)
        and not usuario.tiene_rol(roles.ADMIN, roles.RRHH)
    )


def relaciones(queryset, usuario):
    if supervisor_restringido(usuario):
        return queryset.filter(supervisor=usuario, estado="ACTIVA")
    return queryset


def novedades(queryset, usuario):
    if supervisor_restringido(usuario):
        return queryset.filter(
            relacion_laboral__supervisor=usuario,
            relacion_laboral__estado="ACTIVA",
        )
    return queryset


def documentos(queryset, usuario):
    if supervisor_restringido(usuario):
        return queryset.filter(
            relacion_laboral__supervisor=usuario,
            relacion_laboral__estado="ACTIVA",
        )
    return queryset


def empleados_activos(queryset, usuario):
    if supervisor_restringido(usuario):
        return queryset.filter(
            relaciones__estado="ACTIVA",
            relaciones__supervisor=usuario,
        )
    return queryset.filter(relaciones__estado="ACTIVA")
