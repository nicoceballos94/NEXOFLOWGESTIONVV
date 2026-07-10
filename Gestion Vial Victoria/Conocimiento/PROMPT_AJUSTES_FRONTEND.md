# Prompt para Claude Design — ajustes al proyecto "# Sistema RRHH Corrientes"

> Copiar y pegar el bloque de abajo (entre los `---`) en el chat del proyecto de Claude Design.
> Origen: cross-check §21 de `DISENO_TECNICO_BACKEND.md` + contratos reales de la app
> `novedades` ya implementada en el backend (verificada contra Postgres, 2026-07-10).
> Los contratos de API definitivos están al final de este archivo ("Contratos reales"),
> como referencia para el cableado posterior — no hace falta pegarlos en Claude Design.

---

Necesito 5 ajustes para alinear el prototipo con el backend (Django/DRF) que ya está definido. No cambies el estilo visual ni la estructura general, solo esto:

**1. Estados de novedad (unificar).** Hoy conviven "Registrada / En proceso / Aprobada / Pendiente / Cerrada" en la lista y "Validado / Injustificado" en el formulario. Separalos en dos conceptos:
- **Estado (workflow):** Registrada → En proceso → Aprobada / Rechazada → Cerrada (+ Anulada). Eliminá "Pendiente" (equivale a Registrada). Toda novedad nace en **Registrada**.
- **Clasificación (solo para faltas y licencias):** Justificada / Injustificada — como campo aparte en el form y como badge secundario en la lista.

**2. UI de prórroga de licencia.** En el detalle de una novedad de tipo Licencia/Accidente **Aprobada**, agregá un botón **"Prorrogar"** que abre un mini-form con:
- **Nueva fecha de fin** (obligatoria).
- **Motivo** (texto).
- **Certificado recibido: fecha** (opcional) — un campo de fecha "¿cuándo se recibió el certificado?", **no** un sí/no. Si todavía no llegó, se deja vacío.

No pidas la fecha de inicio de la prórroga: **la calcula el sistema** (arranca contigua a la vigencia vigente, el día siguiente). En el detalle mostrá una **línea de tiempo de la cadena**: la novedad original + cada prórroga con sus fechas y estados, y arriba la **"vigencia total"** calculada (desde → hasta, días totales). Las fechas de una novedad aprobada nunca se editan: toda extensión es una prórroga nueva. En la lista de novedades, una licencia con prórrogas se muestra como **UNA fila** (con badge "N prórrogas"), expandible.

**3. Tipo de novedad "Horas extra".** El selector de tipo debe reflejar los tipos reales del sistema: **Falta, Licencia médica, Accidente / ART, Vacaciones, Permiso, Horas extra**. Al elegir **Horas extra**, el form muestra un campo numérico **"Cantidad de horas"** (obligatorio) y oculta el bloque de praxis/certificado. Es carga manual: "el empleado X hizo N horas extra el día Y". (El botón "Prorrogar" del punto 2 solo aplica a Licencia médica y Accidente.)

**4. Ocultar métricas de asistencia (fase posterior).** El dashboard muestra "Llegadas tarde" y "Ausentismo del mes sobre horas trabajadas": todavía no existe fuente de fichadas, así que quitá esas dos tarjetas o marcalas visualmente como "Próximamente — requiere control de fichadas" sin datos. Lo mismo con cualquier referencia a llegadas tarde en Reportes.

**5. Toggle "Exento de marcación".** En el alta/edición de empleado, sección "Datos laborales", agregá un switch **"Exento de marcación"** (default apagado) con ayuda: "El empleado no ficha entrada/salida (no genera ausencias ni tardanzas)".

Además, dos detalles menores: en el form de novedad el campo "Estado: Validado/Injustificado" pasa a llamarse "Clasificación" (punto 1); y en la ficha del empleado mostrá un campo "Legajo" de solo lectura (lo genera el sistema).

---

## Contratos reales de la API `novedades` (referencia para el cableado — NO pegar en Claude Design)

Ya implementados y verificados contra Postgres (2026-07-10). Base: `/api/v1/`.

### Estados y clasificación
- **Estado (workflow):** `REGISTRADA`, `EN_PROCESO`, `APROBADA`, `RECHAZADA`, `CERRADA`, `ANULADA`.
  Hoy el backend expone las transiciones **aprobar / rechazar / anular** (desde `REGISTRADA`).
  `EN_PROCESO` y `CERRADA` existen en el enum pero **todavía no tienen endpoint** de transición
  (se agregan cuando el workflow lo pida). El diseño puede mostrar el ciclo completo.
- **Clasificación:** `clasificacion` = `JUSTIFICADA` | `INJUSTIFICADA` (o vacío). Es un campo aparte
  del estado, no un paso del workflow.

### Catálogo de tipos — `GET /tipos-novedad/`
Cada tipo trae flags que gobiernan la UI: `codigo`, `nombre`, `admite_prorroga`,
`requiere_certificado`, `requiere_cantidad_horas`, `justifica_ausencia`.
El selector de tipo debe leerse de este catálogo (no hardcodear). Sembrados:
`FALTA`, `LICENCIA_MEDICA` (admite_prorroga, requiere_certificado),
`ACCIDENTE` (admite_prorroga, requiere_certificado), `VACACIONES`, `PERMISO`,
`HORAS_EXTRA` (requiere_cantidad_horas).

### Endpoints
| Método | Ruta | Uso |
|---|---|---|
| GET | `/novedades/` | Lista. Por defecto **cadenas colapsadas** (una fila por madre, con `cantidad_prorrogas` y `vigencia_efectiva`). `?expandir_cadenas=true` muestra cada prórroga. Filtros: `empleado`, `tipo` (código), `estado`, `empresa`, `desde`, `hasta`, `q`. |
| POST | `/novedades/` | Alta. Body: `empleado`, `tipo_novedad`, `fecha_desde`, y **`fecha_hasta` o `dias`** (el back calcula `fecha_hasta = fecha_desde + dias − 1`), `cantidad_horas` (si HORAS_EXTRA), `clasificacion`, `motivo`, `observaciones`, `fecha_aviso_empleado`, `requiere_praxis`, `fecha_turno_praxis`, `fecha_fin_estimada`, `fecha_reintegro`, `certificado_recibido_en`. Nace `REGISTRADA`. |
| PATCH | `/novedades/{id}/` | Edición, **solo si está `REGISTRADA`**. |
| POST | `/novedades/{id}/aprobar/` | → `APROBADA`. Rol RRHH/Admin. |
| POST | `/novedades/{id}/rechazar/` | → `RECHAZADA`. Body opcional `{motivo}`. Rol RRHH/Admin. |
| POST | `/novedades/{id}/anular/` | → `ANULADA`. Bloqueado si es la madre con prórrogas activas. Rol RRHH/Admin. |
| POST | `/novedades/{id}/prorrogar/` | Crea la prórroga. Body: **`{fecha_hasta_nueva, motivo?, certificado_recibido_en?}`**. El back calcula la fecha de inicio (contigua) y hereda el tipo. Si `{id}` es una prórroga, redirige a la madre. Nace `REGISTRADA`. |
| GET | `/novedades/{id}/cadena/` | Línea de tiempo: `{madre, prorrogas[], vigencia_efectiva:{desde,hasta}, dias_totales}`, ordenado cronológicamente. |

### Notas de mapeo para el front
- **Certificado** = campo **fecha** (`certificado_recibido_en`), no booleano.
- La **vigencia total** y el badge **"N prórrogas"** vienen calculados del backend
  (`vigencia_efectiva` y `cantidad_prorrogas` en cada madre); el front no los computa.
- Carga y prórroga: rol **Supervisor** o superior. Aprobar/rechazar/anular: **RRHH/Admin**.
