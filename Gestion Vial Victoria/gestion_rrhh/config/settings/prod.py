"""Configuración de producción."""
from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")  # obligatorio en prod

# Sin default, a propósito: `base.py` tiene uno ("insegura-solo-para-dev") para que el
# entorno de desarrollo arranque sin configurar nada. Heredarlo acá significaba que prod
# levantaba igual sin la variable, firmando JWTs con una clave que está en el repo — y sin
# decir una palabra. Que explote al arrancar es el comportamiento correcto: es la única
# falla de esta lista que no se nota mirando la app funcionando (A4 del análisis).
SECRET_KEY = env("SECRET_KEY")

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
