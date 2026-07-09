# Frontend — Ceibo RRHH

Frontend del sistema de RRHH, **separado del backend** (`../gestion_rrhh`).

## Flujo de trabajo

1. El front se **diseña en Claude Design** (proyecto "Ceibo RRHH").
2. Se **baja** con `DesignSync get_file` a `design/` (la fuente `*.dc.html` + `support.js`).
   Esos archivos son **pristinos: no se editan a mano**.
3. `build.py` **inyecta el cableado** al backend (shims que llaman a `window.CeiboAPI`,
   definido en `integration/ceibo-api.js`) y escribe `dist/`.
4. Se sirve `dist/` como estático apuntando al backend Django.

```
frontend/
├── design/                     # bajado de Claude Design — NO editar
│   ├── Ceibo RRHH standalone-src.dc.html
│   └── support.js              # runtime de Claude Design (carga React solo)
├── integration/
│   └── ceibo-api.js            # capa de integración con la API (lo único a mano)
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

## Qué está cableado (contra la API de empleados)

- **Lista + filtros** (empresa / sector / estado / búsqueda) y **ficha** (datos,
  historial de relación laboral, documentos) → datos reales de Postgres.
- **Alta** de empleado (crea empleado + relación ACTIVA).
- **Editar** (datos personales: nombre, apellido, email, teléfono).
- **Dar de baja** (baja lógica: finaliza la relación con fecha + motivo).
- **Reingreso** (nueva relación ACTIVA).

**Mock / pendiente de backend:** Dashboard (KPIs), Novedades, alertas y reportes
usan datos de ejemplo hasta que existan esas apps en el backend. El alta de
documentos no tiene UI en el diseño (los documentos se muestran, no se cargan).

## Notas

- **Login dev único** embebido en `ceibo-api.js` (usuario `admin`). Se reemplaza
  por login real por usuario más adelante.
- El `legajo` se autogenera en el alta (el diseño no tiene ese campo).
- Si `build.py` corta con "ancla no encontrada", el diseño cambió de forma que
  rompió un anclaje: revisar la edición señalada en `build.py`.
