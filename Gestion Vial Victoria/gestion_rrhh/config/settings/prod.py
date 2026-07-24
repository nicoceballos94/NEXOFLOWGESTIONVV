"""Configuración de producción."""
from .base import *  # noqa: F401,F403
from .base import env, valor_entorno_o_archivo

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")  # obligatorio en prod

# WhiteNoise solo pertenece al runtime de producción. Insertarlo aquí evita advertencias
# y trabajo innecesario en desarrollo, donde los estáticos los sirve runserver.
MIDDLEWARE.insert(  # noqa: F405
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

# Sin default, a propósito: `base.py` tiene uno ("insegura-solo-para-dev") para que el
# entorno de desarrollo arranque sin configurar nada. Heredarlo acá significaba que prod
# levantaba igual con una clave de sesión conocida y sin decir una palabra. Que explote al
# arrancar es el comportamiento correcto: es la única
# falla de esta lista que no se nota mirando la app funcionando (A4 del análisis).
SECRET_KEY = valor_entorno_o_archivo("SECRET_KEY")

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=8 * 60 * 60)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

SECURE_HSTS_SECONDS = env.int(
    "SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Un cache de archivo vive en el tmpfs privado del contenedor y, a diferencia de
# LocMemCache, es compartido por todos los workers de Gunicorn. Esto evita que cada worker
# mantenga su propio contador del throttle de login. Para más de una réplica de API se debe
# migrar este backend a Redis antes de escalar.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": env("CACHE_LOCATION", default="/tmp/django-cache"),
        "TIMEOUT": 300,
        "OPTIONS": {
            "MAX_ENTRIES": 10_000,
        },
    }
}

# Conexiones persistentes cortas, con validación antes de reutilizarlas tras un reinicio de
# PostgreSQL.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)  # noqa: F405
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True  # noqa: F405

# Nginx Proxy Manager termina TLS y reemplaza X-Forwarded-Proto antes de reenviar.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
AUDIT_TRUST_X_FORWARDED_FOR = True

# No se habilita preload por accidente: exige una decisión sobre todo el dominio y es
# difícil de revertir una vez enviado a los navegadores. Las demás advertencias de
# `check --deploy` siguen siendo bloqueantes en CI.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
