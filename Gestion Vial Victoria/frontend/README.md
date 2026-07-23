# Frontend — Ceibo RRHH

Frontend del sistema de RRHH, **separado del backend** (`../gestion_rrhh`).

## Flujo de trabajo

1. El front se **diseña en Claude Design** (proyecto "Ceibo RRHH").
2. Se **baja** con `DesignSync get_file`. La primera importación vive en `design/`
   (la fuente `*.dc.html` + `support.js`); esos archivos son **pristinos: no se
   editan a mano**. Los cambios visuales nuevos **no se bajan directo a `design/`**:
   entran por `design-inbox/` siguiendo el flujo de
   [Design Change Intake](docs/design-change-intake.md).
3. `build.py` **inyecta el cableado** al backend (shims que llaman a `window.CeiboAPI`,
   definido en `integration/ceibo-api.js`) y escribe `dist/`.
4. Se sirve `dist/` como estático apuntando al backend Django.

```
frontend/
├── design/                     # bajado de Claude Design — NO editar
│   ├── Ceibo RRHH standalone-src.dc.html
│   └── support.js              # runtime de Claude Design (carga React solo)
├── design-inbox/               # exports nuevos de Claude Design (referencia, no producción)
│   └── AAAA-MM-DD-nombre/      # un cambio visual por subcarpeta fechada
├── docs/
│   ├── design-change-intake.md   # flujo para traer cambios visuales
│   └── design-change-template.md # plantilla para pedir un cambio
├── integration/
│   └── ceibo-api.js            # capa de integración con la API (lo único a mano)
├── tests/
│   └── test_invariantes_diseno.py  # el guard de build.py corta ante rediseños peligrosos
├── build.py                    # inyecta el cableado → dist/
└── dist/                       # generado (gitignored)
```

## Cómo correrlo

Requiere el backend andando (`cd ../gestion_rrhh && docker compose up`), con
CORS abierto en dev (ya configurado) y Postgres con datos.

```bash
cd frontend
python build.py
cd dist && python -m http.server 8080
# abrir http://127.0.0.1:8080
```

El layout móvil (media queries y clases `ceibo-*-row`) vive en el canvas, no acá, así
que `build.py` no puede cortar por "ancla no encontrada" si un rediseño lo rompe. Esa
red la pone `verificar_invariantes()`, y este test comprueba que efectivamente atrapa
algo — conviene correrlo después de promover un export:

```bash
python frontend/tests/test_invariantes_diseno.py
```

## Qué está cableado (contra la API real de Postgres)

**Empleados**
- **Lista + filtros** (empresa / sector / estado / búsqueda) y **ficha** (datos,
  historial de relación laboral, documentos) → datos reales de Postgres.
- **Alta** de empleado (crea empleado + relación ACTIVA).
- **Editar** (datos personales: nombre, apellido, email, teléfono).
- **Dar de baja** (baja lógica: finaliza la relación con fecha + motivo).
- **Reingreso** (nueva relación ACTIVA).

**Documentos** — alta, edición, borrado, subida y descarga de archivo, con
estado de vencimiento, desde la ficha del empleado.

**Novedades** — cargar, editar, aprobar / rechazar / anular, **prórroga** de
licencias y certificados / adjuntos.

**Dashboard, reportes y alertas** — el panel (KPIs y ranking de faltas), los
reportes de **dotación / ausentismo / rotación** y las **alertas del día**
(vencimientos, cumpleaños, aniversarios, certificados pendientes) salen del
backend real (`apps/dashboard`). De los mocks del canvas solo se reutilizan los
íconos SVG, nunca los datos.

**Configuración** — alta / edición y baja lógica de empresas, sectores y
**tipos de documento** (CU-31).

**Pendiente de backend (fuera de lo cableado hoy):** auditoría consultable
(historial de "quién hizo qué y cuándo") e importación inicial desde Excel.

## Notas

- **Login real por usuario:** cada persona abre sesión con sus credenciales
  contra `/auth/token/` (JWT), y el rol del backend define qué acciones de
  escritura ve (capacidades servidas en `/mi/perfil/`). El front usa las
  capacidades solo para esconder botones; la seguridad real es el 403 del backend.
- El `legajo` se autogenera en el alta (el diseño no tiene ese campo).
- Si `build.py` corta con "ancla no encontrada", el diseño cambió de forma que
  rompió un anclaje: revisar la edición señalada en `build.py`.
