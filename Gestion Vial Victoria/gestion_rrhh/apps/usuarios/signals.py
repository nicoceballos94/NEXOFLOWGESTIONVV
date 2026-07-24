"""Red de integridad para no dejar equipos activos sin un supervisor utilizable."""

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed, pre_save
from django.dispatch import receiver

from common import roles

from .models import Usuario


def _tiene_equipo_activo(usuario: Usuario) -> bool:
    return bool(
        usuario.pk
        and usuario.relaciones_supervisadas.filter(estado="ACTIVA").exists()
    )


@receiver(pre_save, sender=Usuario)
def impedir_desactivar_supervisor_con_equipo(sender, instance, **kwargs):
    if instance.pk and not instance.is_active and _tiene_equipo_activo(instance):
        raise ValidationError(
            {
                "is_active": (
                    "Reasigná o quitá primero todas las relaciones laborales activas "
                    "a cargo de este supervisor."
                )
            }
        )


@receiver(m2m_changed, sender=Usuario.groups.through)
def preservar_roles_de_supervisores_con_equipo(
    sender,
    instance,
    action,
    reverse,
    model,
    pk_set,
    **kwargs,
):
    if action not in {"pre_add", "pre_remove", "pre_clear"}:
        return

    if reverse:
        if not isinstance(instance, Group):
            return
        ids_afectados = (
            list(pk_set)
            if pk_set
            else list(instance.user_set.values_list("pk", flat=True))
        )
        # ``ManyRelatedManager`` ejecuta las señales pre_* dentro de atomic. La fila de
        # Usuario es el mutex compartido con la asignación de relaciones laborales.
        usuarios_bloqueados = Usuario.objects.select_for_update().filter(
            pk__in=sorted(ids_afectados)
        )
        list(usuarios_bloqueados.values_list("pk", flat=True))

        if action == "pre_add" and ids_afectados:
            if instance.name == roles.SERVICIO:
                mezclados = usuarios_bloqueados.filter(
                    groups__name__in=Group.objects.exclude(
                        name=roles.SERVICIO
                    ).values("name")
                )
            else:
                mezclados = usuarios_bloqueados.filter(
                    groups__name=roles.SERVICIO
                )
            if mezclados.exists():
                raise ValidationError(
                    {
                        "groups": (
                            "El rol Servicio es exclusivo y no se combina con roles "
                            "de acceso humano."
                        )
                    }
                )

        usuarios = usuarios_bloqueados.filter(
            relaciones_supervisadas__estado="ACTIVA"
        ).distinct()
        toca_supervisor = (
            instance.name == roles.SUPERVISOR
            and action in {"pre_remove", "pre_clear"}
        )
        toca_servicio = instance.name == roles.SERVICIO and action == "pre_add"
        if (toca_supervisor or toca_servicio) and usuarios.exists():
            raise ValidationError(
                {
                    "groups": (
                        "El cambio afectaría supervisores con empleados activos a cargo. "
                        "Reasigná primero sus equipos."
                    )
                }
            )
        return

    if not isinstance(instance, Usuario):
        return
    # La operación M2M y la asignación de equipo toman este lock común. Cualquiera que
    # llegue segunda vuelve a validar contra el estado ya confirmado por la primera.
    Usuario.objects.select_for_update().filter(pk=instance.pk).exists()

    grupos_actuales = set(instance.groups.values_list("name", flat=True))
    afectados = (
        set(Group.objects.filter(pk__in=pk_set).values_list("name", flat=True))
        if pk_set
        else set()
    )
    if action == "pre_add":
        resultado = grupos_actuales | afectados
        if roles.SERVICIO in resultado and resultado != {roles.SERVICIO}:
            raise ValidationError(
                {
                    "groups": (
                        "El rol Servicio es exclusivo y no se combina con roles "
                        "de acceso humano."
                    )
                }
            )

    if not _tiene_equipo_activo(instance):
        return

    quita_supervisor = (
        action == "pre_clear"
        and roles.SUPERVISOR in grupos_actuales
    ) or (
        action == "pre_remove"
        and roles.SUPERVISOR in afectados
    )
    agrega_servicio = action == "pre_add" and roles.SERVICIO in afectados
    if quita_supervisor or agrega_servicio:
        raise ValidationError(
            {
                "groups": (
                    "Este usuario tiene empleados activos a cargo: debe conservar el rol "
                    "Supervisor y no puede convertirse en una identidad de Servicio."
                )
            }
        )
