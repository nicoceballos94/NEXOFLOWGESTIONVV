# Gestión Vial Victoria — reglas del repo

## Estructura

- `gestion_rrhh/` — backend Django (API). Se verifica siempre contra **Postgres**
  vía `docker compose up` (nunca SQLite).
- `frontend/` — frontend Ceibo RRHH. Ver `frontend/README.md` para la arquitectura.
- `Conocimiento/` — specs y documentos de diseño funcional.

## Fuente de verdad

- **El repo Git es la única fuente de verdad del producto** (código, cableado,
  documentación).
- Para la **UI**, el canvas de Claude Design ("Ceibo RRHH") es la fuente del
  *diseño visual*, y su export vive en `frontend/design/`. Pero el diseño **no es
  la app**: la app real es `dist/`, generada por `frontend/build.py`, que inyecta
  el cableado al backend definido en `frontend/integration/ceibo-api.js`.
- Si hay conflicto entre lo que dice Claude Design y lo que hay en el repo,
  **gana el repo**, salvo indicación explícita del usuario.

## Reglas obligatorias para cambios visuales (Design Change Intake)

El proceso completo está en `frontend/docs/design-change-intake.md`. Resumen:

1. **Nunca editar a mano** los archivos de `frontend/design/` (`*.dc.html`,
   `support.js`). Son el export pristino de Claude Design.
2. **Nunca pisar con un export** los archivos vivos del repo: `frontend/build.py`,
   `frontend/integration/ceibo-api.js`, ni nada de `gestion_rrhh/`. Los ajustes
   hechos por Claude Code viven ahí y deben preservarse siempre.
3. Todo export nuevo de Claude Design entra **primero** por
   `frontend/design-inbox/AAAA-MM-DD-nombre-del-cambio/`. Los archivos del inbox
   son referencia visual, no código de producción.
4. Antes de promover un export a `frontend/design/`, comparar (diff) contra el
   diseño actual y **explicar qué se va a cambiar**.
5. Después de promover, correr `python frontend/build.py`. Si corta con
   "ancla no encontrada", ajustar el anclaje en `build.py` conscientemente,
   explicando el cambio; nunca silenciar el error.
6. Antes de commitear/publicar, mostrar diff o resumen de archivos modificados.
7. Si un cambio visual requiere eliminar código existente (anclas, shims,
   lógica de integración), pedir confirmación o explicarlo claramente antes.
8. **No hacer deploy sin confirmación explícita** (hoy no hay deploy; la regla
   aplica cuando exista).

## Backend

- Verificar siempre contra Postgres: `cd gestion_rrhh && docker compose up`.
- El front local se sirve desde `frontend/dist/` (ver `frontend/README.md`).
