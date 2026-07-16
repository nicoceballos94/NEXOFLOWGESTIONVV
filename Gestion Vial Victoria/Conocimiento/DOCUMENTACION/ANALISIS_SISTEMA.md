# Análisis del sistema — qué anda mal y qué se puede mejorar

**Alcance:** backend `gestion_rrhh/` (Django + DRF + Postgres) y frontend `frontend/`
(canvas de Claude Design + capa de integración `ceibo-api.js` + `build.py`).
**Fecha:** 2026-07-14 · rama `fase-0-verificada`.
**Última actualización:** 2026-07-15 — las secciones **B (correctitud e integridad)** y
**C (robustez y rendimiento)** están **resueltas**; sus hallazgos se quitaron de este
documento (ver "B. Correctitud…" y "C. Robustez…" abajo).

Cada hallazgo tiene un ID (A = seguridad, B = correctitud/integridad, C = robustez,
D = mejoras) y referencia a archivo y línea. Al final hay una tabla de prioridades.

---

## Lo que está bien (contexto)

Antes de los problemas, vale decir que la base es sólida y mejor que el promedio
de un MVP:

- Arquitectura limpia y consistente: views flacas → services (escritura,
  transaccional) → selectors (lectura scopeada por rol). Se cumple en todas las apps.
- Reglas de dominio bien pensadas y documentadas en el código (R1, R10, R11,
  RP1–RP7, cadena de prórrogas con vigencia calculada y nunca persistida).
- Constraints reales en la base (UNIQUE parcial para R1, UNIQUE de documento
  vigente) además de la validación amigable en el service.
- JWT con rotación y blacklist, throttling, manejador de errores JSON uniforme,
  OpenAPI como contrato, paginación con tope.
- Tests de API en todas las apps; seeds reproducibles; docker compose con healthcheck.
- El pipeline del frontend (design intake → `build.py` con anclas que fallan
  ruidosamente → `dist/`) es ingenioso y está bien protegido contra pisadas.

---

## A. Seguridad

### A1 — Credenciales de admin hardcodeadas en el frontend 🔴
`frontend/integration/ceibo-api.js:14-18`

```js
var CONFIG = { API: "...", USER: "admin", PASS: "Clave-Segura-123" };
```

Cualquiera que abra el front (o el repo) tiene la clave de un superusuario, y la app
no tiene pantalla de login: todo visitante ES admin. Todo el sistema de roles del
backend (Admin/RRHH/Supervisor/Empleado) queda sin efecto en la práctica.
Es un atajo de MVP conocido, pero es **lo primero** a resolver antes de cualquier
deploy o de dar acceso a terceros. Además la clave ya quedó en el historial de git:
cuando exista un entorno real, rotarla.

**Fix:** pantalla de login que pida usuario/clave contra `/auth/token/` y guarde el
refresh en memoria (o sessionStorage), y eliminar `USER`/`PASS` de `CONFIG`.

### A2 — Fuga de scope: cualquier autenticado ve documentos de cualquier empleado 🔴
`gestion_rrhh/apps/empleados/api/views.py:73-78`

La acción `documentos` (GET) tiene permiso `IsAuthenticated`, pero resuelve el
empleado con `get_object_or_404(Empleado, pk=pk)` **sin pasar por el selector**.
El scoping por rol ("el Empleado ve solo su ficha") se aplica en `list`/`retrieve`
vía `get_queryset()`, pero acá se lo saltea: un usuario con rol Empleado puede
pedir `GET /api/v1/empleados/{cualquier_id}/documentos/` y ver los documentos
(número, vencimientos, observaciones) de cualquier otra persona.

**Fix:** `empleado = get_object_or_404(self.get_queryset(), pk=pk)` en la rama GET
(las acciones de escritura ya exigen RRHH/Admin, ahí no hay fuga).

### A3 — PII expuesta a roles que no deberían verla 🟠
`gestion_rrhh/apps/empleados/api/serializers.py:36-65` vs. la promesa de
`gestion_rrhh/apps/empleados/models.py:52` ("El PII (dni/cuil) se expone solo a
RRHH/Admin").

`EmpleadoSerializer` es único para todos los roles: un **Supervisor** (que ve toda la
dotación) recibe dni, cuil, dirección, teléfono, contacto de emergencia, obra social
y observaciones de todos. El modelo documenta otra intención.

**Fix:** serializer reducido (sin PII) para Supervisor, o campos condicionales por
rol en `to_representation`.

### A4 — `SECRET_KEY` con default inseguro alcanza también a prod 🟠
`gestion_rrhh/config/settings/base.py:17` y `prod.py`

`SECRET_KEY = env("SECRET_KEY", default="insegura-solo-para-dev")` vive en `base.py`
y `prod.py` no lo redefine: si en prod falta la variable de entorno, el proceso
**arranca igual** con la clave insegura (firmando JWTs con ella).

**Fix:** en `prod.py`, `SECRET_KEY = env("SECRET_KEY")` sin default, para que prod
explote al arrancar si falta.

---

## B. Correctitud e integridad de datos ✅ resuelta (2026-07-15)

Los seis hallazgos (B1–B6) están arreglados y verificados contra Postgres. Se quitan
de este documento; quedan acá solo el registro de qué se hizo y las consecuencias que
sobreviven al fix. Detalle en el commit y en los tests que los cubren.

| ID | Era | Quedó |
|---|---|---|
| B1 | Filtro empresa+estado usaba un JOIN por `.filter()` y cada condición la satisfacía una relación distinta | `empresa`/`sector`/`estado` se combinan en un solo `.filter()` — `empleados/selectors.py` |
| B2 | El PATCH podía romper la cadena de prórrogas (`fecha_desde`, `tipo_novedad`) | `actualizar_novedad` los rechaza si `novedad.es_prorroga` |
| B3 | El no-solapamiento solo vivía en Python (SELECT+INSERT, carrera abierta) | Lock pesimista sobre el empleado + `ExclusionConstraint` con `btree_gist` |
| B4 | Un documento cargado no se podía corregir ni renovar | `PATCH`/`DELETE` de `/empleados/{id}/documentos/{doc_id}/` |
| B5 | El legajo lo calculaba el navegador con `max+1` | Lo asigna el backend con advisory lock; el cliente no puede elegirlo |
| B6 | `todayISO()` devolvía la fecha UTC (de noche, mañana) | Se arma con getters locales |

**Un bug extra, no detectado en el análisis original:** prorrogar una cadena que ya
tenía una prórroga sin aprobar creaba **dos eslabones solapados arrancando el mismo
día** — `vigencia_efectiva` solo avanza con las APROBADAS, y la validación de
solapamiento no lo veía porque excluye la cadena entera. Ahora la cadena avanza de a
un eslabón resuelto por vez. Sin este fix, B3 hacía explotar ese flujo con un
`IntegrityError`.

**Consecuencias que quedan vivas:**
- **El fallback a sqlite murió**: `DATABASE_URL` es obligatoria y las migraciones solo
  corren en Postgres (el `ExclusionConstraint` no existe en sqlite). Ya era la regla de
  `CLAUDE.md`, pero antes el código la toleraba.
- **`Novedad.ocupa_periodo` es un dato denormalizado** (copia del flag del tipo, mantenida
  en `save()`), porque un `ExclusionConstraint` no puede hacer JOIN a `TipoNovedad`. Si
  algún día se cambia `ocupa_periodo` en un `TipoNovedad` ya usado, las novedades viejas
  conservan el valor con el que se cargaron: hay que backfillear a mano.
- **Los locks de concurrencia no tienen test** (una carrera real no es testeable con la
  infra actual). Para novedades no importa demasiado: el `ExclusionConstraint` es la
  garantía dura y sí está testeado. Para el legajo no hay red equivalente — si el
  advisory lock fallara, el UNIQUE tira el mismo error críptico de antes.
- **B4 quedó deliberadamente mínimo**: sin flag `vigente` ni historial de versiones.
  Renovar un apto médico es mover su `fecha_vencimiento`. La decisión de versionar
  espera al módulo de documentos con archivos (Drive/OneDrive + metadata en base).

---

## C. Robustez y rendimiento ✅ resuelta (2026-07-15)

Los cinco hallazgos (C1–C5) están arreglados y verificados contra Postgres (112 tests en
verde + medición de queries sobre la base real + la app corriendo en el navegador). Se
quitan de este documento; queda acá el registro de qué se hizo y las consecuencias que
sobreviven al fix.

| ID | Era | Quedó |
|---|---|---|
| C1 | `activo` hacía `.filter().exists()`, que ignora el prefetch: una query **por empleado** listado | Se resuelve sobre `relaciones.all()` — serializar 12 empleados pasó de **12 queries a 0** |
| C2 | La serie de rotación disparaba 4 COUNT por mes; el panel abría con **71 queries** (este documento decía ~50: estaba corto, medido son 71) | `_Dotacion` lee las relaciones **una vez** y cuenta en memoria — **71 → 5 queries** |
| C3 | `getAllPages` no miraba `r.ok`: un 401/429/500 devolvía lista parcial y la UI decía "0 empleados" sin error | Lanza error como `jget`; `page_size` 200 → 100 (el tope real del backend, antes se clampeaba en silencio) |
| C4 | Login y refresh compartían el scope `login` (5/min): varias pestañas renovando cortaban sesiones válidas | Scope `refresh` propio a 30/min — verificado: 8 refresh seguidos no gastan el cupo del login |
| C5 | El no-solapamiento traía **todas** las novedades del empleado y descartaba por fecha en Python | El rango se filtra en SQL, sobre el índice GiST que ya trae el `ExclusionConstraint` |

**Consecuencias que quedan vivas:**
- **El dashboard ahora carga la dotación en memoria.** `_Dotacion` trae
  `(empleado_id, estado, fecha_ingreso, fecha_egreso)` de todas las relaciones. Con miles
  de filas son unas pocas tuplas; en **decenas de miles** habría que volver a agregación en
  SQL. El umbral está documentado en el docstring de la clase, que es donde se va a leer.
- **Cuidado con la asimetría al tocar `_Dotacion`**: `activos_*` cuenta **personas**
  distintas, `ingresos_en`/`egresos_en` cuentan **relaciones** (dos altas de la misma
  persona son dos ingresos). Es la semántica que ya tenían las queries, y es lo primero que
  se rompe al reescribir. La red es `test_dashboard_api.py`, que fija `hoy` y afirma
  números exactos.
- **Efecto lateral a favor:** las 71 queries eran 71 snapshots, así que una escritura
  concurrente a mitad de render podía dejar el KPI de activos peleado con la serie de
  rotación. Una sola lectura es un solo snapshot y eso desapareció.
- **C3 cambia el comportamiento a propósito:** donde antes había una lista a medias sin
  aviso, ahora hay una excepción. Es lo buscado (un fallo tiene que romper ruidoso, no
  mentir), pero es un cambio real: un endpoint caído ahora se ve.
- **`_se_solapan` ya no existe.** El predicado vivía en Python y ahora es
  `_filtro_solapadas_con` (un `Q`), para no tener la misma regla escrita dos veces y que
  se desincronicen. Se traduce 1:1, incluido el rango abierto (`fecha_hasta` NULL), que
  necesita `isnull=True` explícito porque en SQL `fecha_hasta >= x` con NULL no matchea.
- **Los throttles no tienen test automatizado**: C4 se verificó a mano contra la API viva
  (8 refresh → 401 sin 429; el 6º login fallido → 429). Un scope mal escrito explota al
  arrancar, así que el riesgo de que se rompa en silencio es bajo, pero un test de 429
  seguiría siendo mejor que esta nota.

---

## D. Mejoras funcionales y de proceso

### D1 — Workflow de novedades incompleto
`EN_PROCESO` y `CERRADA` existen en el enum (`novedades/models.py:15-23`) pero no
tienen endpoint de transición; el front los mapea a "sin acción"
(`ceibo-api.js:152-154`). O se implementan (`/tomar/`, `/cerrar/`) o se quitan del
contrato hasta que existan.

### D2 — Sin auditoría (RP8)
El TODO está declarado en `novedades/services.py:7-9`: no hay `RegistroAuditoria`.
Hoy solo se sabe quién creó (`creado_por`) y quién aprobó (`aprobada_por`); rechazos,
anulaciones, ediciones y bajas no registran actor ni momento (el motivo se concatena
en `observaciones`, que es frágil). Para RRHH —dominio con disputas legales— es de
las mejoras de más valor.

### D3 — Alertas de vencimiento: está el dato, falta el proceso
`DocumentoEmpleado.fecha_vencimiento` está indexado "para la query de alertas",
`Parametro` existe para los días de aviso, `Empresa.referente_rrhh` es "el
destinatario de avisos"… pero no hay ningún job/endpoint/consumidor que los use.
Los tres están muertos hoy. Un endpoint `GET /documentos/por-vencer/` + panel en el
dashboard sería el primer paso natural (n8n puede consumirlo después).

### D4 — Sin adjuntos
No hay `FileField` en todo el sistema: certificados médicos y documentos son solo
metadata (fechas y números). Está bien para MVP1, pero conviene decidir dónde
vivirán los archivos (S3/local) antes de que el modelo crezca.

### D5 — El front carga todo en memoria
`listEmpleados`/`listNovedades` traen **todas** las páginas y filtran client-side.
Con cientos de registros va bien; con miles, la carga inicial y el ranking van a
doler. El backend ya soporta filtros y paginación — el front podría usarlos cuando
duela (no antes).

### D6 — `getOrCreatePuesto` crea catálogo por texto libre
`ceibo-api.js:248-256`: un typo en "Chofer"/"chofer "/"Choferr" crea puestos
duplicados que después ensucian filtros. Mejor un `<select>` con opción "crear
nuevo…" explícita.

### D7 — Sin CI
No hay `.github/workflows`. Hay tests y ruff configurados (`pyproject.toml`) pero
nada los corre automáticamente. Un workflow mínimo (ruff + pytest contra Postgres
de servicio + `python frontend/build.py` para validar anclas) protegería justo los
puntos frágiles del proyecto.

### D8 — Detalles menores del front
- `anios()` (`ceibo-api.js:118-121`): muestra mínimo "1 años" para cualquier
  antigüedad menor a un año, y "1 años" es gramaticalmente incorrecto → "6 meses" /
  "1 año".
- `splitName()` (`ceibo-api.js:113-117`): "Juan Carlos Pérez" → nombre "Juan",
  apellido "Carlos Pérez". Heurística inevitable con un solo campo; considerar dos
  campos en el canvas.
- Novedades filtradas por empresa dependen de `relacion_laboral` no nulo
  (`novedades/selectors.py:49-50`): una novedad sin relación asociada desaparece de
  ese filtro (el dashboard ya lo resuelve aparte; la lista no).

---

## Prioridades sugeridas

Las secciones B y C salieron de esta tabla: están resueltas (2026-07-15). Lo que queda
pendiente es **toda la sección A** y las mejoras de D.

| Prioridad | ID | Hallazgo | Esfuerzo |
|---|---|---|---|
| 🔴 1 | A1 | Login real; sacar credenciales hardcodeadas | Medio |
| 🔴 2 | A2 | Scope en `GET /empleados/{id}/documentos/` | Trivial (1 línea) |
| 🟠 3 | A3 | PII solo para RRHH/Admin | Bajo |
| 🟠 4 | A4 | `SECRET_KEY` sin default en prod | Trivial |
| 🟢 5 | D7 | CI mínima | Bajo |
| 🟢 6 | D2 | Auditoría (RP8) | Alto |
| 🟢 7 | D3 | Alertas de vencimiento | Medio |
| 🟢 — | resto | D1, D4, D5, D6, D8 | según roadmap |

**Lo próximo, sin vueltas:** ahora la única sección roja es la de seguridad. A2 es una
línea y hoy cualquier usuario con rol Empleado puede leer los documentos de cualquier otra
persona. A1 es lo que vuelve real a todo el sistema de roles (hoy todo visitante es
admin). Ninguno de los dos se arregló acá: rendimiento y robustez ya están, seguridad no.
