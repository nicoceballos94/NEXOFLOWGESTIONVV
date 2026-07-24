from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    name = "apps.usuarios"
    label = "usuarios"
    verbose_name = "Usuarios y accesos"

    def ready(self):
        from . import signals  # noqa: F401
