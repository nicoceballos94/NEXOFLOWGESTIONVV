"""Consultas de usuarios que exponen catálogos operativos mínimos."""

from django.db.models import QuerySet

from common import roles

from .models import Usuario


def supervisores_asignables(*, activo: bool | None = True) -> QuerySet[Usuario]:
    """Usuarios humanos con pertenencia real al grupo Supervisor.

    ``tiene_rol`` considera al superusuario miembro de cualquier rol. Para asignar una
    dotación eso sería demasiado amplio: el responsable debe pertenecer explícitamente al
    grupo Supervisor. También se excluye cualquier identidad de Servicio aunque tenga
    grupos mezclados por una mala configuración.
    """
    qs = (
        Usuario.objects.filter(groups__name=roles.SUPERVISOR)
        .exclude(groups__name=roles.SERVICIO)
        .distinct()
    )
    if activo is not None:
        qs = qs.filter(is_active=activo)
    return qs.order_by("first_name", "last_name", "username", "id")
