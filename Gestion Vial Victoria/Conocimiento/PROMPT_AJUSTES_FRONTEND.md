# Prompt para Claude Design — ajustes al proyecto "# Sistema RRHH Corrientes"

> Copiar y pegar el bloque de abajo en el chat del proyecto de Claude Design.
> Origen: cross-check §21 de `DISENO_TECNICO_BACKEND.md` (2026-07-07).

---

Necesito 5 ajustes para alinear el prototipo con el backend (Django/DRF) que ya está definido. No cambies el estilo visual ni la estructura general, solo esto:

**1. Estados de novedad (unificar).** Hoy conviven "Registrada / En proceso / Aprobada / Pendiente / Cerrada" en la lista y "Validado / Injustificado" en el formulario. Separalos en dos conceptos:
- **Estado (workflow):** Registrada → En proceso → Aprobada / Rechazada → Cerrada (+ Anulada). Eliminá "Pendiente" (equivale a Registrada).
- **Clasificación (solo para faltas y licencias):** Justificada / Injustificada — como campo aparte en el form y como badge secundario en la lista.

**2. UI de prórroga de licencia.** En el detalle de una novedad de tipo Licencia/Accidente APROBADA, agregá un botón **"Prorrogar"** que abre un mini-form (nueva fecha de fin, motivo, certificado recibido sí/no). Y en el detalle mostrá una **línea de tiempo de la cadena**: novedad original + cada prórroga con sus fechas y estados, y arriba la "vigencia total" calculada (desde → hasta, días totales). Las fechas de una novedad aprobada nunca se editan: toda extensión es una prórroga nueva. En la lista de novedades, una licencia con prórrogas se muestra como UNA fila (con badge "N prórrogas"), expandible.

**3. Tipo de novedad "Horas extra".** Agregalo al selector de tipo en "Registrar novedad". Cuando se elige, el form muestra un campo numérico **"Cantidad de horas"** (obligatorio) y oculta el bloque de praxis/certificado. Es carga manual: "empleado X hizo N horas extra el día Y".

**4. Ocultar métricas de asistencia (fase posterior).** El dashboard muestra "Llegadas tarde" y "Ausentismo del mes sobre horas trabajadas": todavía no existe fuente de fichadas, así que quitá esas dos tarjetas o marcalas visualmente como "Próximamente — requiere control de fichadas" sin datos. Lo mismo con cualquier referencia a llegadas tarde en Reportes.

**5. Toggle "Exento de marcación".** En el alta/edición de empleado, sección "Datos laborales", agregá un switch **"Exento de marcación"** (default apagado) con ayuda: "El empleado no ficha entrada/salida (no genera ausencias ni tardanzas)".

Además, dos detalles menores: en el form de novedad el campo "Estado: Validado/Injustificado" pasa a llamarse "Clasificación" (punto 1); y en la ficha del empleado mostrá un campo "Legajo" de solo lectura (lo genera el sistema).

---

*Referencia de contratos de API que va a consumir cada pantalla: ver §8 y §6 bis de `DISENO_TECNICO_BACKEND.md`. La cadena de prórrogas se consume de `GET /api/v1/novedades/{id}/cadena/` → `{madre, prorrogas[], vigencia_efectiva{desde,hasta}, dias_totales}`.*
