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
