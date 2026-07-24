"""Configuración base — compartida por dev y prod.

Convenciones del proyecto (ver Conocimiento/DISENO_TECNICO_BACKEND.md):
- Dominio en español, código idiomático en inglés donde corresponda.
- Todo en UTC en DB; zona operativa América/Argentina/Buenos Aires (P5).
"""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="insegura-solo-para-dev")
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
    "rest_framework_simplejwt.token_blacklist",
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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
DATABASES = {"default": env.db("DATABASE_URL")}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "usuarios.Usuario"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
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
DOCUMENTO_EXTENSIONES = ("pdf", "jpg", "jpeg", "png", "webp", "heic")

# Foto de perfil del empleado: solo imágenes raster (sin PDF ni SVG). Se sirve inline por el
# mismo tipo de endpoint protegido que los documentos; el SVG queda afuera porque se ejecuta
# como HTML en el navegador y esta imagen sí se muestra en vez de descargarse.
FOTO_MAX_BYTES = env.int("FOTO_MAX_BYTES", default=5 * 1024 * 1024)  # 5 MB
FOTO_EXTENSIONES = ("jpg", "jpeg", "png", "webp", "heic")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
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
        # Scope propio, y no el de `login`: compartirlo hacía que varias pestañas renovando
        # su access (dura 15 min) se comieran los 5/min y cortaran sesiones válidas, y de
        # paso le regalaba cupo a un ataque de fuerza bruta contra el login. El refresh ya
        # exige un token válido, así que puede ser holgado sin aflojar la puerta.
        "refresh": "30/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(hours=12),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

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
# El front corre en otro origen y descarga los respaldos con fetch (necesita mandar el
# header Authorization, cosa que un <a href> no hace). De una respuesta cross-origin, el
# navegador solo deja leer a JS un puñado de headers: Content-Disposition no está entre
# ellos salvo que el servidor lo exponga. Sin esto, el nombre que arma la vista no llega
# y el apto médico se descarga como "documento", sin extensión ni con qué abrirlo.
CORS_EXPOSE_HEADERS = ["Content-Disposition"]
