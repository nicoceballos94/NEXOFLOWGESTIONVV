# Design Change Intake — cambios visuales desde Claude Design

Flujo para traer cambios visuales del canvas de Claude Design ("Ceibo RRHH")
**sin perder** el cableado al backend que vive en el repo.

## Por qué este flujo

La arquitectura del frontend separa diseño y cableado:

- `design/` — export pristino de Claude Design. **No se edita a mano.**
- `integration/ceibo-api.js` — capa de integración con la API Django (a mano).
- `build.py` — inyecta el cableado en el diseño mediante anclas deterministas
  y genera `dist/`. Si un ancla no aparece, **corta con error** en vez de
  fallar en silencio.

Gracias a esto, re-bajar el diseño **no puede pisar** los ajustes de Claude
Code: viven fuera del export. El riesgo real es que un rediseño **rompa un
anclaje** o cambie estructura que el cableado asume. Este flujo agrega un paso
de revisión antes de promover cualquier export.

## Conexión con Claude Design (DesignSync)

El canvas vive en Claude Design y se accede con la tool **DesignSync** (MCP de
Anthropic, autorizado en la sesión con `/design-login`). **No es un MCP a
configurar en `.mcp.json`**: ya viene en el harness.

- **projectId**: `6146d4a1-1905-4bba-8d9a-335e1c43b2bd`
  (nombre interno "# Sistema RRHH Corrientes", dueño "Nico").
- **Gotcha**: es `PROJECT_TYPE_PROJECT`, así que `DesignSync list_projects`
  devuelve **vacío** (filtra a design-system). Usar `get_project` / `list_files`
  / `get_file` con el `projectId` **directo** — funcionan igual.
Sincronía en las dos direcciones (regla, ver `CLAUDE.md`):

- **Bajar (canvas → repo)** — cuando el usuario avisa que cambió el canvas:
  `get_file` de `Ceibo RRHH.dc.html` y `support.js` (devuelve JSON `{content}`;
  extraer `content` al inbox) y correr el intake de abajo.
- **Subir (repo → canvas)** — cuando Claude Code hace un cambio **visual**:
  aplicarlo en el repo y además `write_files` para reflejarlo en el canvas, así
  el canvas sigue siendo la fuente del diseño visual. **Solo lo visual**: el
  cableado (`ceibo-api.js`, shims de `build.py`) **nunca** se sube al canvas.

## El flujo, paso a paso

### Paso 1 — Bajar el export al inbox

Bajar el canvas actualizado (DesignSync `get_file`, projectId arriba) a una
subcarpeta nueva:

```
frontend/design-inbox/AAAA-MM-DD-nombre-del-cambio/
```

Opcionalmente, completar la plantilla `docs/design-change-template.md` como
`notas.md` en esa carpeta (recomendado para cambios grandes).

**Nunca** bajar directo a `design/`.

### Paso 2 — Leer el cambio como referencia

Claude Code lee el export del inbox como **referencia visual**, no lo copia a
ningún lado todavía.

### Paso 3 — Comparar

```bash
git diff --no-index "frontend/design/Ceibo RRHH.dc.html" "frontend/design-inbox/<carpeta>/Ceibo RRHH.dc.html"
```

Claude Code debe determinar y explicar:

- **Qué pide el nuevo diseño** (cambios visuales/estructurales).
- **Qué existe hoy** en el repo para esa pantalla/sección.
- **Qué ajustes previos hay que preservar** (shims de `build.py`, lógica de
  `ceibo-api.js`).
- **Si alguna ancla de `build.py` deja de existir** en el export nuevo
  (buscar cada ancla de `EDICIONES` en el HTML nuevo).
- **Qué archivos vivos deben modificarse** (normalmente: `design/*.dc.html`
  por promoción; a veces anclas de `build.py`; rara vez `ceibo-api.js`).

### Paso 4 — Promover y aplicar solo lo necesario

Con el análisis explicado (y confirmación del usuario si hay que eliminar o
reescribir código existente):

1. Copiar el export del inbox a `design/` (reemplaza el `.dc.html` y, si vino,
   `support.js`).
2. Correr `python build.py`.
3. Si corta con "ancla no encontrada", ajustar el ancla en `build.py` para que
   la inyección siga aplicando sobre el HTML nuevo, explicando cada ajuste.

### Paso 5 — Verificar y reportar

Probar en local:

```bash
cd gestion_rrhh && docker compose up   # backend
cd frontend && python build.py
cd dist && python -m http.server 8080  # abrir http://127.0.0.1:8080
```

Claude Code debe mostrar al final:

- Archivos modificados.
- Cambios visuales aplicados.
- Ajustes previos preservados (y anclas retocadas, si hubo).
- Posibles diferencias respecto a Claude Design.
- Comandos para probar localmente.

Recién entonces se commitea (mostrando el diff/resumen antes). La subcarpeta
del inbox puede eliminarse una vez commiteado el cambio.

## Reglas (ver también CLAUDE.md en la raíz)

- El repo Git es la única fuente de verdad; si hay conflicto con Claude Design,
  gana el repo salvo indicación contraria.
- `design/` no se edita a mano; `build.py` y `integration/` no se pisan con
  exports.
- Todo export entra por `design-inbox/`; nada del inbox es producción.
- No hacer deploy sin confirmación explícita.
