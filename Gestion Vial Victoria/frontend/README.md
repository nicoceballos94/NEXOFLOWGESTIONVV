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
│   ├── test_invariantes_diseno.py  # corta ante rediseños peligrosos
│   └── test_guardas_frontend.py    # sesión+CSRF, API same-origin, DOM, IDs y transiciones
├── build.py                    # inyecta el cableado → dist/
├── dev_server.py               # estáticos + proxy /api/ para desarrollo same-origin
└── dist/                       # generado (gitignored)
```

## Cómo correrlo

Requiere el backend andando (`cd ../gestion_rrhh && docker compose up`) y
Postgres con datos. El frontend usa `/api/v1` relativo también en desarrollo:
`dev_server.py` sirve `dist/` y deriva `/api/` a Django, bajo un único origen.

```bash
cd frontend
python build.py
python dev_server.py
# abrir http://127.0.0.1:8080
```

Para otro puerto/backend local:

```bash
CEIBO_PORT=8081 CEIBO_BACKEND=http://127.0.0.1:8000 python dev_server.py
```

El layout móvil (media queries y clases `ceibo-*-row`) vive en el canvas, no acá, así
que `build.py` no puede cortar por "ancla no encontrada" si un rediseño lo rompe. Esa
red la pone `verificar_invariantes()`, y este test comprueba que efectivamente atrapa
algo — conviene correrlo después de promover un export:

```bash
python frontend/tests/test_invariantes_diseno.py
python frontend/tests/test_guardas_frontend.py
```

## Qué está cableado (contra la API real de Postgres)

**Empleados**
- **Lista + filtros** (empresa / sector / estado / búsqueda) y **ficha** (datos,
  historial de relación laboral, documentos) → datos reales de Postgres.
- **Alta** de empleado (crea empleado + relación ACTIVA con empresa, sector y puesto).
- **Editar** datos personales y la asignación vigente (sector, puesto, jornada y
  contrato), respetando los flujos históricos de empresa/ingreso/baja.
- **Asignar supervisor** explícito a la relación activa.
- **Dar de baja** (baja lógica: finaliza la relación con fecha + motivo).
- **Reingreso** (nueva relación ACTIVA y vuelve a pedir empresa, sector, puesto, fecha y
  onboarding/documentación).

**Documentos** — alta, edición, borrado, subida y descarga de archivo, con
estado de vencimiento, desde la ficha del empleado.

**Novedades** — cargar, editar y recorrer el flujo explícito **Tomar / Aprobar /
Rechazar / Cerrar / Anular**, además de **prórrogas** y certificados / adjuntos.
Una novedad nueva no puede simular `Cerrada` desde el alta: el cierre usa
`POST /novedades/{id}/cerrar/` y queda registrado por el backend.

**Dashboard, reportes y alertas** — el panel (KPIs y ranking de faltas), los
reportes de **dotación / ausentismo / rotación** y las **alertas del día**
(vencimientos, cumpleaños, aniversarios, certificados pendientes) salen del
backend real (`apps/dashboard`). De los mocks del canvas solo se reutilizan los
íconos SVG, nunca los datos.

**Configuración** — alta / edición y baja lógica de empresas, sectores y
puestos por sector, tipos de documento y plantillas versionadas de
onboarding/offboarding por empresa+sector.

**Auditoría** — bitácora consultable por Admin, filtros y resumen dentro de cada ficha.
Registra cambios y lecturas sensibles; el backend la protege como append-only.

**Diferido fuera del MVP1:** importación inicial desde Excel, salvo que se confirme una
fuente real que justifique construirla.

## Notas

- **Sesión Django same-origin:** el front obtiene CSRF en `/auth/csrf/`, abre la
  sesión con `POST /auth/login/` y la cierra con `POST /auth/logout/`. La cookie
  de sesión es HttpOnly; no se guardan credenciales de API en storage del navegador.
  Para cada `POST` / `PUT` / `PATCH` / `DELETE`, el cliente relee `csrftoken`
  de la cookie —incluido después del login, cuando Django lo rota— y envía
  `X-CSRFToken`. Un `401` limpia los datos visibles y devuelve al login.
- El rol del backend define qué acciones de escritura se muestran (capacidades
  servidas en `/mi/perfil/`). El front solo esconde botones; la seguridad real
  sigue siendo el `403` del backend.
- El `legajo` se autogenera en el alta y se muestra tal como lo devuelve el backend.
- Si `build.py` corta con "ancla no encontrada", el diseño cambió de forma que
  rompió un anclaje: revisar la edición señalada en `build.py`.
