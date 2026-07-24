from django.contrib.auth.models import AbstractUser

from common import roles


class Usuario(AbstractUser):
    """Usuario del sistema. Los roles se manejan por Grupos (§7).

    En MVP1 se agrega la FK opcional a Empleado (app empleados).
    """

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    @property
    def roles(self) -> list[str]:
        return list(self.groups.values_list("name", flat=True))

    def tiene_rol(self, *nombres: str) -> bool:
        if self.is_superuser:
            return True
        return self.groups.filter(name__in=nombres).exists()

    @property
    def es_admin(self) -> bool:
        return self.tiene_rol(roles.ADMIN)

    @property
    def es_rrhh(self) -> bool:
        return self.tiene_rol(roles.RRHH)

    @property
    def empleado_auditado(self) -> None:
        """Un evento sobre un usuario no es de nadie en particular (ver `auditoria.services`).

        Devuelve None **a propósito**, incluso cuando el usuario está enlazado a un empleado:
        darle un rol a alguien es un hecho del sistema, no de su legajo. Atarlo a la persona
        pondría "ascendido a Admin" en la pestaña Historial de su ficha de RRHH, mezclando
        dos historias que se leen por motivos distintos.

        Se declara explícito y no se omite para que "no tiene la propiedad" signifique
        siempre "se la olvidaron", nunca "no aplica".
        """
        return None
