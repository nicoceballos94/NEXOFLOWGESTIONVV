# Gestión RRHH — Grupo Vial Victoria

Backend Django + DRF + PostgreSQL (monolito modular). Diseño completo en
[`../Conocimiento/DISENO_TECNICO_BACKEND.md`](../Conocimiento/DISENO_TECNICO_BACKEND.md).

## Estado

**Fase 0 (fundaciones)** — usuarios/roles, empresas/sectores/puestos, JWT, OpenAPI.
Próxima: Fase 1/MVP1 (empleados + novedades con prórrogas).

## Requisitos

Instalar **una** de las dos opciones:
- **Docker Desktop** (recomendado, incluye Postgres), o
- **Python 3.12+** (desde https://python.org — con sqlite alcanza para Fase 0; desde MVP1 se necesita Postgres).

## Levantar con Docker

```bash
cd gestion_rrhh
copy .env.example .env      # (o cp en bash) y editar SECRET_KEY
docker compose up --build
```

Queda en http://localhost:8000 — con migraciones aplicadas y seed inicial
(roles + empresas VIAL VICTORIA/PREMOCOR + sectores) ya corrido.

## Levantar sin Docker (Python local)

```bash
cd gestion_rrhh
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements-dev.txt
python manage.py makemigrations usuarios organizacion
python manage.py migrate
python manage.py seed_inicial
python manage.py createsuperuser
python manage.py runserver
```

## URLs clave

| URL | Qué es |
|---|---|
| `/api/docs/` | Swagger UI (probar la API a mano) |
| `/api/schema/` | OpenAPI YAML — **contrato con el frontend de Claude Design** |
| `/api/v1/auth/token/` | Login JWT (`{username, password}` → `{access, refresh}`) |
| `/api/v1/mi/perfil/` | Usuario autenticado + roles |
| `/api/v1/empresas/` · `/sectores/` · `/puestos/` | Catálogos organizativos |
| `/admin/` | Django admin |

## Tests y lint

```bash
pytest
ruff check .
```

## Convenciones (resumen del diseño §9–§12)

- Dominio en **español**; cada app: `models` / `services` (escritura) / `selectors` (lectura) / `api/`.
- Views flacas: orquestan, no deciden. Reglas de negocio en services con `@transaction.atomic`.
- Transiciones de estado = endpoints de acción (`/aprobar/`), nunca PATCH del campo estado.
- Sin DELETE físico en entidades de dominio (baja lógica, R10).
