from django.apps import AppConfig


class CommonConfig(AppConfig):
    name = "common"
    verbose_name = "Común"

    def ready(self):
        # drf-spectacular descubre sus extensiones al importar el módulo.
        # La importación explícita evita que el esquema omita silenciosamente
        # la autenticación por cookie usada por toda la API.
        from . import schema  # noqa: F401
