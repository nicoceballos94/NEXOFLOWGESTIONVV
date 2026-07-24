"""Configuración de desarrollo."""
from pathlib import Path

import environ

# Solo desarrollo lee el archivo local. Producción recibe variables y secretos montados.
environ.Env.read_env(Path(__file__).resolve().parents[2] / ".env")

from .base import *  # noqa: E402,F401,F403
from .base import env  # noqa: E402

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True
# Permite probar el frontend same-origin detrás de un proxy local en otro puerto. Vacío
# por defecto: Django continúa usando su comprobación de mismo origen normal.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
