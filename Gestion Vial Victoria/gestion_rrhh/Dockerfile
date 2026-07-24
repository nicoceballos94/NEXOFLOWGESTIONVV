# Digest del manifest multi-arquitectura: el mismo commit siempre parte de la misma base.
FROM python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# IDs altos y deterministas: evitan colisiones con cuentas del host y mantienen estable
# el ownership del volumen media entre releases.
RUN addgroup -S -g 10001 app \
    && adduser -S -D -H -u 10001 -G app app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.txt

# Copias explícitas: el contexto nunca aporta .env, media, tests, caches ni el virtualenv.
COPY --chown=app:app manage.py ./
COPY --chown=app:app config ./config
COPY --chown=app:app common ./common
COPY --chown=app:app apps ./apps

RUN mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app/staticfiles /app/media

USER app

# Los estáticos quedan dentro de la imagen y WhiteNoise los sirve sin un volumen mutable.
# Estas credenciales son valores inertes de build; collectstatic no abre una conexión a DB.
RUN SECRET_KEY="build-only-not-a-production-secret-7db5ef18c9b84f97" \
    DATABASE_URL="postgresql://build:build@127.0.0.1/build" \
    ALLOWED_HOSTS="localhost" \
    DJANGO_SETTINGS_MODULE="config.settings.prod" \
    python manage.py collectstatic --noinput

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; hosts=[h.strip() for h in os.environ.get('ALLOWED_HOSTS','localhost').split(',') if h.strip()]; candidate=hosts[0] if hosts else 'localhost'; host=('health'+candidate if candidate.startswith('.') else ('localhost' if candidate == '*' else candidate)); request=urllib.request.Request('http://127.0.0.1:8000/healthz/', headers={'Host': host, 'X-Forwarded-Proto': 'https'}); urllib.request.urlopen(request, timeout=3).close()"]

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "--graceful-timeout", "25", "--keep-alive", "5", "--max-requests", "1000", "--max-requests-jitter", "100", "--error-logfile", "-"]
