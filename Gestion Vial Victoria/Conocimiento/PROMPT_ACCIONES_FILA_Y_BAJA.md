# Prompt para Claude Design — acciones por fila en la cadena + fecha de egreso en baja + limpiar alta

> Copiar y pegar el bloque de abajo (entre los `---`) en el chat del proyecto de Claude Design.
> Origen: feedback de uso (2026-07-10). Extiende a `PROMPT_NOVEDADES_ACCIONES.md`: aquella suma
> acciones en el **pie** del detalle (actúan sobre la novedad madre); esta suma acciones **por fila**
> a cada **prórroga** de la cadena, y corrige dos cosas de Empleados (fecha de egreso en la baja, y
> sacar el bloque de egreso del alta). Los contratos de API reales están al final ("Contratos
> reales") como referencia para el cableado — no pegar en Claude Design.
>
> **Variante a decidir antes de pegar:** este prompt mantiene las acciones de la **madre en el pie**
> (como ya están) y agrega acciones inline **solo en las filas de prórroga**. Si preferís unificar
> —mismo set de botones inline en **todas** las filas (madre incluida) y dejar el pie solo con
> "Cerrar"— avisá y ajusto el prompt; es un cambio de una línea.

---

Tengo tres ajustes de UI. No cambies el estilo visual general ni la estructura de los modales; sumá/quitá solo lo que se indica, reusando los estilos que ya existen.

## 1. Acciones por fila en la cadena de la novedad

En el modal de **detalle de una novedad**, la sección "Cadena de la novedad" muestra una línea de tiempo con la **novedad original** y, debajo, cada **prórroga** (con su rango de fechas, su motivo y su badge de estado).

Hoy solo se puede actuar sobre la novedad original (con los botones del pie del modal). Necesito poder actuar sobre **cada prórroga por separado**, porque una prórroga nace en estado "Registrada" y hay que poder editarla, aprobarla, rechazarla o anularla sin tocar el resto de la cadena.

Debajo de cada **fila de prórroga** (no de la novedad original), agregá una fila de botones **compactos** (más chicos que los del pie), con su visibilidad decidida por el **estado de esa prórroga**:

- **Editar** — visible **solo si esa prórroga está en estado "Registrada"**. Abre el formulario "Registrar novedad" en **modo edición** (título "Editar novedad", campos precargados con los datos de esa prórroga), igual que el "Editar" del pie del detalle.
- **Aprobar** — botón primario verde, compacto. Visible si el estado de la prórroga es **"Registrada" o "En proceso"**.
- **Rechazar** — visible si el estado es **"Registrada" o "En proceso"**.
- **Anular** — discreto, rojo tenue. Visible si el estado **no es terminal** (ocultarlo cuando la prórroga ya está "Anulada", "Rechazada" o "Cerrada").

La **novedad original** (primera fila de la cadena) **no** lleva estos botones inline: sus acciones siguen estando en el **pie del modal** (las que ya existen: Editar / Aprobar / Rechazar / Anular / Cerrar). Mantené el botón **"Prorrogar"** donde está.

Los botones inline deben ser visualmente consistentes con los del pie (mismos colores por acción: Aprobar verde, Rechazar/Anular en rojo, Editar neutro) pero en tamaño reducido para no competir con la jerarquía del pie.

## 2. Fecha de egreso en el modal de baja

En el modal **"Dar de baja a {empleado}"** (Empleados → ficha → Dar de baja), hoy solo se pide **"Motivo de baja"**. Agregá **arriba del motivo** un campo **"Fecha de egreso"**: un input de fecha `dd/mm/aaaa` con el mismo selector de calendario que usan los demás campos de fecha del sistema (el del alta de empleado, por ejemplo). El campo es opcional en la UI (si se deja vacío se asume la fecha de hoy), pero debe estar visible para poder registrar una baja con fecha distinta a hoy.

## 3. Quitar el bloque "Egreso" del alta de empleado

En el modal de **"Alta de empleado"** hay una sección **"Egreso — completar al dar de baja"** con los campos **Fecha de egreso** y **Motivo de egreso**. Esa sección **no corresponde al alta** (el egreso se registra desde el modal de baja, ver punto 2). **Eliminá** la sección "Egreso" completa del formulario de alta.

---

## Contratos reales (referencia para el cableado — NO pegar en Claude Design)

Ya implementados en el backend. Base `/api/v1/`.

### Acciones por fila (cada prórroga es una novedad con su propio `id`)

| Acción del botón | Llamada a la API | Condición |
|---|---|---|
| Editar (guardar) | `PATCH /novedades/{idProrroga}/` | Solo si la prórroga está en REGISTRADA |
| Aprobar | `POST /novedades/{idProrroga}/aprobar/` | Desde REGISTRADA o EN_PROCESO; rol RRHH/Admin |
| Rechazar | `POST /novedades/{idProrroga}/rechazar/` (body opc. `{motivo}`) | Desde REGISTRADA o EN_PROCESO; RRHH/Admin |
| Anular | `POST /novedades/{idProrroga}/anular/` (body opc. `{motivo}`) | Anular una prórroga no toca el resto de la cadena; RRHH/Admin |

- Las prórrogas nacen **REGISTRADA** (RP5) y heredan el tipo de la madre; por eso normalmente tendrán visibles Editar/Aprobar/Rechazar/Anular.
- La visibilidad por estado la maneja el view-model del detalle (igual que `puedeProrrogar` / `canEdit`), así funciona con datos reales. Cada ítem de la línea de tiempo debe exponer el `id` de su prórroga para poder cablear el `onClick`.

### Baja de empleado

| Acción | Llamada a la API | Nota |
|---|---|---|
| Confirmar baja | `POST /empleados/{id}/relaciones/{relacionActivaId}/finalizar/` con `{fecha_egreso, motivo_egreso}` | El backend **exige** `fecha_egreso` y valida `fecha_egreso >= fecha_ingreso`. Si el campo se deja vacío en la UI, el front manda hoy. |

### Alta de empleado

- El alta (`POST /empleados/`) **no** envía datos de egreso; los campos "Fecha de egreso" / "Motivo de egreso" del alta hoy están muertos, por eso se quitan.

---

## Estado actual en el repo (para Claude Code, no para Claude Design)

Los tres cambios ya están funcionando en `dist/` como **inyecciones de `build.py`** (más el cableado en `integration/ceibo-api.js`). Cuando este export llegue a `frontend/design/`, hay que **adelgazar** esas inyecciones: dejar solo el cableado (handlers `t.*Row`, lectura de la fecha de egreso, etc.) y quitar las que agregan **markup visual** (los botones inline, el input de fecha de egreso, la remoción del bloque Egreso), porque ese markup pasará a venir del canvas. El build tiene que seguir corriendo limpio (`python build.py`).
