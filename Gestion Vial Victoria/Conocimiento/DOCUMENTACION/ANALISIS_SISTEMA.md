# Análisis del sistema — lo que falta arreglar

**Alcance:** backend `gestion_rrhh/` (Django + DRF + Postgres) y frontend `frontend/`
(canvas de Claude Design + capa de integración `ceibo-api.js` + `build.py`).
**Origen:** relevamiento del 2026-07-14, rama `fase-0-verificada`.
**Última actualización:** 2026-07-20 — se verificó **cada hallazgo abierto contra el
código** y se depuró el documento: los cerrados salieron del cuerpo (queda el registro
mínimo en el apéndice). Lo que sigue acá es **solo lo pendiente**. En la misma jornada se
cerraron **A1, A3, A4 y D9**; la suite corre en verde contra Postgres (125 tests, 5
nuevos). Con el login real, la sección A pasa de cuatro hallazgos abiertos a uno (**A5**,
nuevo: la UI todavía no distingue roles).

Cada hallazgo tiene un ID (A = seguridad, D = mejoras) y referencia a archivo y línea.
Al final hay una tabla de prioridades.

**Método:** este documento arrastró hallazgos mal relevados (describían como faltante
código que ya existía). Antes de planificar sobre esta tabla, verificar contra el repo,
y buscar desde la raíz (`NEXOFLOWGESTIONVV/`), no desde `Gestion Vial Victoria/`:
`.github/` vive un nivel más arriba.

---

## A. Seguridad

### A5 — La UI no distingue roles 🟠
`frontend/` (canvas + `build.py`) — abierto desde el 2026-07-20

Con A1 cerrado, cada persona entra con sus credenciales y el backend aplica su rol. Pero
**la UI sigue mostrando todo a todos**: un Supervisor ve "Nuevo empleado", "Aprobar" y
"Editar", y recién al hacer click se come un 403. No es un agujero de seguridad —el
backend rechaza igual— pero es una promesa que la app no cumple.

El diseño ya lo tenía previsto: `Ceibo RRHH.dc.html` documenta que *"el canvas no lo sabe
(no hay sesión) y asume que sí. El cableado lo corrige con el rol real"*, y expone el hook
`puedeAdjuntar`. Los roles reales ya llegan al front: `CeiboAPI.perfilVals()` los lee de
`/mi/perfil/` y hoy solo se usan para el pie del sidebar.

**Fix:** ocultar por rol las acciones de escritura (altas, aprobar/rechazar, editar,
adjuntar), usando el rol de `/mi/perfil/`. Toca markup → entra por el canvas.

**Nota para probarlo:** la base de dev tiene **un solo usuario** (`admin`, superusuario,
sin grupos). No hay con qué probar la vista de un Supervisor ni el recorte de PII de A3
hasta que existan usuarios de prueba con cada rol.

---

## D. Mejoras funcionales y de proceso

### D1 — Workflow de novedades incompleto (backend)
`novedades/models.py:22,26` — verificado abierto 2026-07-20

`EN_PROCESO` y `CERRADA` existen en el enum y **participan de `OCUPAN_PERIODO`**
(`novedades/models.py:33-40`, y por lo tanto del `ExclusionConstraint`), pero **no
tienen endpoint de transición**: las `@action` de `novedades/api/views.py:82-117` son
`aprobar`, `rechazar`, `anular`, `prorrogar` y `cadena`. No hay `/tomar/` ni `/cerrar/`,
y ningún service los produce — hoy solo se llega a esos estados escribiendo en la base.

**Actualizado:** el lado del front **ya se cerró**. `ceibo-api.js:486-495` retira "En
proceso" y "Cerrada" del `<select>` en vez de aceptarlos y no hacer nada; antes la
novedad quedaba Registrada sin avisar. O sea: el contrato ya no le miente al usuario,
pero **el backend sigue con dos estados inalcanzables**. O se implementan (`/tomar/`,
`/cerrar/`) o se quitan del enum.

### D2 — Sin auditoría (RP8)
`novedades/services.py:7-9` — verificado abierto 2026-07-20

El TODO sigue declarado tal cual: no existe `RegistroAuditoria` ni la app `auditoria`
(la búsqueda en todo `gestion_rrhh/` solo encuentra ese TODO). Hoy únicamente se sabe
quién creó (`creado_por`) y quién aprobó (`aprobada_por`); **rechazos, anulaciones,
ediciones y bajas no registran actor ni momento** — el motivo se concatena en
`observaciones`, que es frágil. `empleados` tampoco audita. Para RRHH —dominio con
disputas legales— es de las mejoras de más valor.

### D5 — El front carga todo en memoria
`listEmpleados`/`listNovedades` traen **todas** las páginas y filtran client-side.
Con cientos de registros va bien; con miles, la carga inicial y el ranking van a
doler. El backend ya soporta filtros y paginación — el front podría usarlos cuando
duela (no antes).

### D6 (resto) — El typo sigue creando puestos desde la UI
El backend ya está cerrado (2026-07-16): `Puesto` tiene unicidad case-insensitive por
constraint, el nombre se normaliza al guardar y `POST /puestos/` es idempotente, así que
"Chofer" / "chofer" / "  CHOFER  " colapsan en una sola fila.

**Queda pendiente (UI):** "Choferr" sigue creando un puesto nuevo, porque el campo es
texto libre en el canvas. Lo cierra un `<select>` con "crear nuevo…" explícito, que es
cambio de Claude Design.

---

## Prioridades sugeridas

| Prioridad | ID | Hallazgo | Esfuerzo |
|---|---|---|---|
| 🟠 1 | A5 | Ocultar por rol las acciones que el backend rechaza | Medio |
| 🟢 2 | D2 | Auditoría (RP8) | Alto |
| 🟢 — | resto | D1, D5, D6 (el `<select>` del canvas) | según roadmap |

**Lo próximo, sin vueltas:** con A1 cerrado, el recorte de PII de A3 **recién ahora hace
algo**: hasta hoy el front entraba siempre como superusuario y todo visitante veía todo.
Lo que queda de seguridad es A5, que es de coherencia, no de exposición — el backend ya
rechaza lo que no corresponde. Antes de eso conviene **crear usuarios de prueba por rol**:
sin ellos no hay forma de ver funcionando ni A3 ni A5.

---

## Apéndice — cerrados (registro mínimo)

Se sacaron del cuerpo. Todos se constataron contra el código en `fase-0-verificada` y la
suite corre en verde contra Postgres (120 tests, `docker compose exec api pytest`).

| ID | Qué era | Cerrado |
|---|---|---|
| A1 | Credenciales de admin hardcodeadas; sin pantalla de login | 2026-07-20 |
| A2 | Fuga de scope en documentos de empleado | 2026-07-16 (`_empleado_en_scope()`) |
| A3 | PII de toda la dotación visible para el Supervisor | 2026-07-20 |
| A4 | `SECRET_KEY` con default inseguro heredado por prod | 2026-07-20 |
| D9 | Menores del front (huso en `docEstado`, empresa en `adaptNov`) | 2026-07-20 |
| B1–B6 | Correctitud e integridad de datos | 2026-07-15 |
| C1–C5 | Robustez y rendimiento | 2026-07-15 |
| D3 | Alertas de vencimiento | nunca estuvo pendiente (mal relevado) |
| D4 | Adjuntos | nunca estuvo pendiente (mal relevado) |
| D6 | Catálogo de puestos por texto libre — **backend** | 2026-07-16 (queda la UI, arriba) |
| D7 | CI | 2026-07-16 (`backend-ci.yml` existía; se agregó `frontend-ci.yml`) |
| D8 | Detalles menores del front (`anios()`, novedades por empresa) | 2026-07-16 |

**Consecuencias de esos fixes que siguen vivas** (esto no es deuda pendiente, es
contexto que hay que tener a mano al tocar ese código):

- **El fallback a sqlite murió**: `DATABASE_URL` es obligatoria y las migraciones solo
  corren en Postgres (el `ExclusionConstraint` no existe en sqlite).
- **`Novedad.ocupa_periodo` es un dato denormalizado** (copia del flag del tipo, mantenida
  en `save()`), porque un `ExclusionConstraint` no puede hacer JOIN a `TipoNovedad`. Si se
  cambia `ocupa_periodo` en un `TipoNovedad` ya usado, las novedades viejas conservan el
  valor con el que se cargaron: hay que backfillear a mano.
- **Los locks de concurrencia no tienen test.** Para novedades no importa demasiado: el
  `ExclusionConstraint` es la garantía dura y sí está testeado. Para el legajo no hay red
  equivalente — si el advisory lock fallara, el UNIQUE tira un error críptico.
- **B4 quedó deliberadamente mínimo**: sin flag `vigente` ni historial de versiones.
  Renovar un apto médico es mover su `fecha_vencimiento`.
- **El dashboard carga la dotación en memoria** (`_Dotacion`). Con miles de filas son unas
  pocas tuplas; en **decenas de miles** habría que volver a agregación en SQL. El umbral
  está en el docstring de la clase.
- **Asimetría de `_Dotacion`**: `activos_*` cuenta **personas** distintas,
  `ingresos_en`/`egresos_en` cuentan **relaciones** (dos altas de la misma persona son dos
  ingresos). Es lo primero que se rompe al reescribir; la red es `test_dashboard_api.py`.
- **C3 cambió el comportamiento a propósito:** donde antes había una lista a medias sin
  aviso, ahora hay una excepción. Un endpoint caído ahora se ve.
- **`_se_solapan` ya no existe**: es `_filtro_solapadas_con` (un `Q`), incluido el rango
  abierto (`fecha_hasta` NULL), que necesita `isnull=True` explícito.
- **Los throttles no tienen test automatizado** (C4 se verificó a mano). Un scope mal
  escrito explota al arrancar, así que el riesgo silencioso es bajo.
- **`EmpleadoSerializer` ahora depende del contexto** (A3): recorta `CAMPOS_PII` salvo para
  RRHH/Admin y el titular de la ficha, y **falla cerrado** — sin `request` en el contexto
  oculta el PII. Las tres llamadas manuales de `views.py` pasan `get_serializer_context()`;
  un llamador nuevo que se lo olvide va a ver campos faltantes, no PII de más. Al agregar
  un campo sensible al modelo hay que sumarlo a `CAMPOS_PII`: la lista es explícita, así
  que lo que no está en ella se expone.
- **A4 hace que prod no arranque sin `SECRET_KEY`.** Es lo buscado, pero el día del primer
  deploy la variable tiene que estar antes de levantar el proceso. En dev no cambia nada:
  `base.py` conserva el default y `docker-compose.yml` la inyecta.
- **`docEstado()` corrigió un segundo off-by-one no registrado en el análisis:** además del
  documento que vence HOY (que se pintaba vencido), **"vence en 31 días" caía en amarillo**
  por el mismo corrimiento de huso. Ahora el umbral de 30 días es exacto.
- **La sesión vive en `sessionStorage`** (A1): sobrevive al F5, muere al cerrar la pestaña.
  El access queda solo en memoria. Como cualquier token manejado por JS, es alcanzable por
  un XSS — la mitigación real es no introducir uno, no el lugar donde se guarda.
- **La clave de dev quedó en el historial de git** (y citada en este documento como parte
  del hallazgo). Para dev no importa; **el día que exista un entorno real hay que rotarla**.
- **La carga inicial ya no corre al montar el componente** sino en `cargarTodo()`, después
  del login o de restaurar la sesión. Quien agregue un `reloadX` nuevo tiene que sumarlo
  ahí, no en `componentDidMount`, o no se va a cargar nunca.
- **`logout()` limpia los índices en memoria de `ceibo-api.js`** (empresas, sectores,
  puestos, empleados, tipos). Si se agrega un caché nuevo al módulo, va también ahí: si no,
  el próximo usuario que entre en la misma pestaña ve datos del anterior.
