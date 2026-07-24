"""Configuración base — compartida por dev y prod.

Convenciones del proyecto (ver Conocimiento/DISENO_TECNICO_BACKEND.md):
- Dominio en español, código idiomático en inglés donde corresponda.
- Todo en UTC en DB; zona operativa América/Argentina/Buenos Aires (P5).
"""
import os
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
_SIN_DEFAULT = object()


def valor_entorno_o_archivo(nombre: str, *, default=_SIN_DEFAULT) -> str:
    """Lee NAME_FILE antes que NAME para que producción use secretos montados.

    Docker Compose monta cada secreto como archivo bajo ``/run/secrets``. Mantener el
    contenido fuera del environment evita que aparezca en ``docker inspect``. Desarrollo
    sigue usando las variables cargadas desde ``.env`` por ``dev.py``.
    """
    ruta = os.environ.get(f"{nombre}_FILE")
    if ruta:
        try:
            valor = Path(ruta).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ImproperlyConfigured(
                f"No se pudo leer el secreto {nombre}_FILE."
            ) from exc
        if not valor:
            raise ImproperlyConfigured(f"El secreto {nombre}_FILE está vacío.")
        return valor
    if default is _SIN_DEFAULT:
        return env(nombre)
    return env(nombre, default=default)


SECRET_KEY = valor_entorno_o_archivo(
    "SECRET_KEY", default="insegura-solo-para-dev"
)
DEBUG = False
ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # ExclusionConstraint + btree_gist (novedades)
    # terceros
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    # apps de dominio (monolito modular)
    "common",
    "apps.usuarios",
    "apps.organizacion",
    "apps.empleados",
    "apps.novedades",
    "apps.dashboard",
    "apps.onboarding",
    "apps.auditoria",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "common.middleware.NoCacheAPIMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.auditoria.contexto.ContextoAuditoriaMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Postgres y solo Postgres: el fallback a sqlite murió cuando `novedades` incorporó el
# ExclusionConstraint de solapamiento (btree_gist). Las migraciones no corren en sqlite.
# Levantar la base con `docker compose up` antes de migrar o correr los tests.
_DATABASE_URL = valor_entorno_o_archivo("DATABASE_URL", default="")
if _DATABASE_URL:
    DATABASES = {"default": env.db_url_config(_DATABASE_URL)}
else:
    # Producción evita una URL con contraseña dentro del environment: recibe la contraseña
    # mediante POSTGRES_PASSWORD_FILE y el resto son valores no secretos.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": env("POSTGRES_HOST", default="db"),
            "PORT": env.int("POSTGRES_PORT", default=5432),
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER"),
            "PASSWORD": valor_entorno_o_archivo("POSTGRES_PASSWORD"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "usuarios.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"  # P5: única zona operativa
USE_I18N = True
USE_TZ = True  # se persiste en UTC

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Archivos de respaldo de documentos (CU-06) ---
# Los archivos NO viven en la base: en la columna va la ruta (~80 bytes), el binario va acá.
# `MEDIA_URL` a propósito NO se define y `media/` NO se sirve como estático: un apto médico
# es un dato de salud, así que se descarga solo por el endpoint que valida rol y scope
# (`/empleados/{id}/documentos/{doc_id}/archivo/`). Servirlo por URL directa saltearía el
# login: en `media/` no hay permisos, solo el sistema de archivos.
# Con volumen persistente en docker-compose; migrar a S3/R2 el día del deploy es cambiar
# STORAGES por django-storages, sin tocar el modelo (por eso el FileField y no una URL).
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

# Tope de subida. El default de Django (2.5 MB en memoria) deja pasar archivos enormes a
# disco temporal; acá se corta antes, en el serializer.
DOCUMENTO_MAX_BYTES = env.int("DOCUMENTO_MAX_BYTES", default=10 * 1024 * 1024)  # 10 MB
DOCUMENTO_EXTENSIONES = ("pdf", "jpg", "jpeg", "png", "webp")

# Foto de perfil del empleado: solo imágenes raster (sin PDF ni SVG). Se sirve inline por el
# mismo tipo de endpoint protegido que los documentos; el SVG queda afuera porque se ejecuta
# como HTML en el navegador y esta imagen sí se muestra en vez de descargarse.
FOTO_MAX_BYTES = env.int("FOTO_MAX_BYTES", default=5 * 1024 * 1024)  # 5 MB
FOTO_EXTENSIONES = ("jpg", "jpeg", "png", "webp")
IMAGEN_MAX_PIXELES = env.int("IMAGEN_MAX_PIXELES", default=40_000_000)

# Defensa temprana además del límite de 12 MB en Nginx Proxy Manager. El handler corta
# cada archivo antes de que llegue al serializer o al almacenamiento temporal.
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
FILE_UPLOAD_HANDLERS = [
    "common.uploads.LimiteArchivoUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "common.authentication.SessionAuthentication401",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "common.pagination.PaginacionEstandar",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "common.exceptions.manejador_excepciones",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/min",
        "user": "300/min",
        "login": "5/min",
    },
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
AUDIT_TRUST_X_FORWARDED_FOR = False

SPECTACULAR_SETTINGS = {
    "TITLE": "API Gestión RRHH — Grupo Vial Victoria",
    "DESCRIPTION": (
        "Backend del sistema de RRHH y control de asistencias. "
        "Esta schema es el contrato con el frontend (Claude Design) y con n8n/bots."
    ),
    "VERSION": "0.1.0",
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_EXPOSE_HEADERS = ["Content-Disposition"]
