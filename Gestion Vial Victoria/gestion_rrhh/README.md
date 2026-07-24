# Gestión RRHH — Grupo Vial Victoria

Backend Django/DRF + PostgreSQL y gateway web Nginx del MVP1. El contrato funcional
vigente está en
[`../Conocimiento/ARQUITECTURA_MVP1_PRODUCCION.md`](../Conocimiento/ARQUITECTURA_MVP1_PRODUCCION.md).

## Desarrollo local

Requisitos: Docker Desktop con Compose.

```bash
cd gestion_rrhh
copy .env.example .env
docker compose up --build
```

La API queda en `http://127.0.0.1:8000`. PostgreSQL también se publica únicamente en
loopback para herramientas locales; ninguno de los dos puertos queda expuesto a la LAN.
El Compose de desarrollo aplica migraciones y carga catálogos iniciales. Eso no es un
procedimiento de producción.

La autenticación del navegador usa sesión Django y CSRF, no tokens almacenados en el
frontend:

| URL | Uso |
|---|---|
| `/api/v1/auth/csrf/` | Inicializar la cookie CSRF |
| `/api/v1/auth/login/` | Iniciar sesión |
| `/api/v1/auth/logout/` | Cerrar e invalidar la sesión |
| `/api/v1/mi/perfil/` | Identidad y roles de la sesión |
| `/api/docs/` | Swagger, solo con settings de desarrollo |
| `/api/schema/` | OpenAPI, solo con settings de desarrollo |
| `/healthz/` | Readiness de Django y PostgreSQL |
| `/admin/` | Administración Django |

## Controles locales

```bash
docker compose exec -T api ruff check .
docker compose exec -T api python manage.py makemigrations --check --dry-run
docker compose exec -T api python manage.py spectacular --validate --fail-on-warn --file /tmp/openapi.yaml
docker compose exec -T api pytest
```

Las dependencias están bloqueadas con hashes. Para una instalación fuera de Docker:

```bash
python -m pip install --require-hashes -r requirements-dev.txt
```

PostgreSQL es obligatorio; las restricciones de vigencia y solapamiento no funcionan en
SQLite.

## Producción

El despliegue usa tres servicios persistentes sin puertos publicados:

- `web`: Nginx no privilegiado, sirve el frontend y reenvía API/admin/health a Django.
- `api`: Django + Gunicorn con un rol PostgreSQL runtime sin ownership ni atributos
  privilegiados, visible solo para `web` y PostgreSQL.
- `db`: PostgreSQL, aislado en una red interna. Su imagen reemplaza el `gosu` vulnerable
  de la base oficial por `su-exec` y se vuelve a empaquetar sin conservar la capa retirada.

Además existen jobs de corta vida: `db-provision` crea/restringe el rol runtime,
`migrate` es el único Django que recibe el secreto owner y `db-permissions-check` prueba
que la API puede operar sesiones pero no alterar, deshabilitar triggers ni truncar la
bitácora.

Solo `web` se une a la red externa de Nginx Proxy Manager, con alias `rrhh-web`. El
upstream de NPM es `http://rrhh-web:8080`. `/healthz` atraviesa el gateway y solo responde
OK si Django puede consultar PostgreSQL; `/gateway-healthz` comprueba únicamente el
contenedor web.

Los volúmenes PostgreSQL/media son externos y tienen nombres obligatorios en `.env.prod`;
así un cambio de directorio o nombre de proyecto no puede crear silenciosamente una base
vacía. La imagen API usa el UID/GID estable `10001:10001`, que debe poder escribir en el
volumen media existente.

El procedimiento completo, incluyendo secretos, backup, migraciones, smoke tests y
rollback, está en [`deploy/README.md`](deploy/README.md). No ejecutar en producción
`seed_datos_prueba`, `seed_usuarios_demo` ni el Compose de desarrollo.

## Convenciones

- Reglas y transiciones en servicios de dominio; las views solo orquestan.
- Transiciones de estado mediante acciones explícitas, no por `PATCH` del estado.
- Sin borrado físico de entidades de dominio.
- Archivos sensibles solo mediante endpoints autenticados; `media/` nunca se sirve como
  directorio público.
