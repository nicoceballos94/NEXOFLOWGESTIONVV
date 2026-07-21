# Módulo RRHH — Especificación funcional

## 0. Arquitectura propuesta (consistente con lo que ya usás)

Mismo patrón que el resto de tus automatizaciones: **n8n como orquestador + Google Sheets/Excel como base de datos liviana + Telegram como canal**, con Claude Code vía MCP para implementar cada workflow.

```
Google Sheets "EMPLEADOS" (EMPLEADOS / RELACION_LABORAL / NOVEDADES)
        │
        ├── Workflow "CRUD Empleados" (alta/baja lógica/edición) → trigger manual o form
        │
        ├── Workflow "Alertas Diarias" (cron 7:00 AM)
        │     └── recorre RELACION_LABORAL + NOVEDADES → arma mensajes → Telegram (RRHH)
        │
        ├── Workflow "Alertas Mensuales" (cron día 1, 8:00 AM)
        │     └── antigüedad, rotación, métricas del mes → Telegram + resumen a Sheet "Reportes"
        │
        └── Workflow "Cross-check Novedades" (cron diario)
              └── compara fechas (vencimientos, certificados, praxis) → genera NOVEDAD automática si corresponde
```

No hace falta sistema nuevo: el Excel que ya armamos es la base. Si el volumen de empleados crece mucho, ahí sí conviene migrar a una DB real (Postgres/Airtable), pero para arrancar Sheets alcanza y es más rápido de iterar.

---

## 1. MVP1 — Funcionalidades

### 1.1 CRUD Empleados
| Acción | Cómo se hace | Detalle |
|---|---|---|
| Alta | Form en n8n o edición directa en Sheet | Escribe en `EMPLEADOS` + crea primer registro en `RELACION_LABORAL` (ESTADO=ACTIVA) |
| Modificación | Edición directa o workflow con botones Telegram | Actualiza fila existente |
| Baja | **Baja lógica**, nunca DELETE físico | Cambia `RELACION_LABORAL.ESTADO` a `FINALIZADA` + completa `FECHA EGRESO` y `MOTIVO EGRESO`. El registro en `EMPLEADOS` nunca se borra |

**Por qué baja lógica:** necesitás el historial para antigüedad, rotación y reincorporaciones (ver que ya tenés el caso de DAMIAN con 2 relaciones laborales en PREMOCOR).

### 1.2 Alta y modificación de Novedades
- Formulario/bot para cargar: tipo (ACCIDENTE / FALTA / LICENCIA / VACACIONES), motivo, fechas, si requiere praxis.
- Edición de una novedad existente (ej: ampliar licencia, como el caso real que ya tenés: novedad 1 con "pie roto" ampliada por la novedad 2).

### 1.3 Alertas diarias (cron cada mañana)
Un solo workflow, un solo mensaje consolidado a Telegram con estas secciones (solo si hay contenido, para no mandar mensajes vacíos):

| Alerta | Condición (sobre tu estructura actual) |
|---|---|
| Cumpleaños hoy | `EMPLEADOS.FECHA DE NACIMIENTO` = hoy (día/mes) |
| Contrato por vencer | Si manejás contratos a plazo, campo a agregar en `RELACION_LABORAL`: `FECHA VENCIMIENTO CONTRATO` ≤ hoy + N días |
| Carnet vencido / por vencer | Campo a agregar (no existe aún): `CARNET_VTO` en `EMPLEADOS` o tabla aparte por tipo de carnet (conducir, manipulación alimentos, etc.) |
| Apto médico vencido / por vencer | Campo a agregar: `APTO_MEDICO_VTO` |
| CNRT vencida | Campo a agregar: `CNRT_VTO` (aplica a choferes de Vial Victoria/Premocor) |
| Enfermedad/accidente sin certificado | `NOVEDADES` donde `TIPO` ∈ (ACCIDENTE, ENFERMEDAD) y `FECHA CERTIFICADO RECIBIDO` está vacío y ya pasaron X días de `FECHA` |
| Certificados pendientes | Igual al anterior, listado aparte |
| Enviado a Praxis sin confirmación | `FECHA TURNO PRAXIS` cargada pero sin resultado/confirmación asociada (hoy no hay campo de "confirmado" — falta agregarlo) |

**Nota:** tu Excel actual no tiene todavía los campos de vencimientos (carnet, apto médico, CNRT, contrato). Es el primer gap a cerrar antes de programar las alertas — si querés te agrego esas columnas al `EMPLEADOS.xlsx` ya mismo.

### 1.4 Generación automática de novedades por cross-check
Ejemplo concreto con tu dato real: la novedad 3 (FALTA, INJUSTIFICADO, "NO AVISA") podría auto-generarse si en algún momento tenés un registro de asistencia (fichada/API de control horario) y el sistema detecta ausencia sin novedad de licencia/vacaciones que la justifique ese día. Sin fuente de asistencia todavía, este punto queda bloqueado hasta que definas de dónde sale el dato de presentismo (ver MVP2 "API control de llegadas tarde" — es la misma fuente).

### 1.5 Mensajes de aviso a empleados (según parametría)
Mismos disparadores que 1.3 pero el destinatario es el empleado (no RRHH), vía Telegram/WhatsApp si tenés el teléfono cargado (`EMPLEADOS.TELÉFONO`, hoy vacío en tu archivo — hay que completarlo).

### 1.6 Métricas (dashboard o reporte mensual)

**Dotación**
- Empleados activos = `COUNTIF(RELACION_LABORAL.ESTADO="ACTIVA")` (por persona única, cuidado con duplicados si alguien tiene 2 relaciones)
- Ingresos del mes = altas con `FECHA INGRESO` en el mes
- Egresos del mes = bajas con `FECHA EGRESO` en el mes

**Ausentismo** (fuente: `NOVEDADES`)
- Total faltas = `COUNT(TIPO="FALTA")` en el período
- Justificadas / injustificadas = split por `ESTADO`
- Llegadas tarde = requiere fuente de asistencia (no está en el Excel hoy)
- Promedio por empleado = total faltas / empleados activos

**Rotación**
- Rotación mensual = (egresos del mes) / (activos promedio del mes) × 100
- Rotación anual = acumulado 12 meses
- Motivos principales = agrupar `RELACION_LABORAL.MOTIVO EGRESO`

**Ranking**
- Más faltas / más llegadas tarde = `TOP N` agrupando `NOVEDADES` por `ID_PERSONA` (hoy se agrupa por `ID_RELACION_LABORAL`, ver nota abajo)

### 1.7 Antigüedad (cron mensual)
Recorre `RELACION_LABORAL` con `ESTADO=ACTIVA`, calcula años desde `FECHA INGRESO`, y si el aniversario cae ese mes → alerta "cumple 1/2/3... año(s)".

---

## 2. Gaps a resolver antes de programar (importante)

1. **Falta de campos de vencimiento** en `EMPLEADOS.xlsx`: carnet, apto médico, CNRT, contrato. Sin esto no hay alertas 1.3 posibles.
2. **Sin fuente de asistencia/llegadas tarde**: no hay forma de calcular ausentismo real ni ranking de puntualidad sin un sistema de fichada o API (esto es justo el ítem de MVP2 "API control de llegadas tarde" — convendría adelantarlo porque bloquea 3 métricas de MVP1).
3. **NOVEDADES apunta a `ID_RELACION_LABORAL`, no a `ID_PERSONA` directamente**: para rankings "por empleado" hay que hacer join `NOVEDADES → RELACION_LABORAL → ID_PERSONA`. Funciona, pero hay que tenerlo claro al armar las fórmulas/queries.
4. **Teléfono vacío en `EMPLEADOS`**: necesario para mandar avisos directo al empleado (punto 1.5).

---

## 3. MVP2 — Backlog (ya priorizable, no ambiguo)

| Item | Qué es en concreto | Depende de |
|---|---|---|
| Medidas disciplinarias | Tabla nueva: apercibimientos/suspensiones ligada a `ID_PERSONA`, con motivo y fecha | Nada, se puede armar ya |
| ~~Carga de documentación~~ **✅ HECHO en MVP1** | Se implementó con almacenamiento propio (no Drive): `DocumentoEmpleado` con archivo de respaldo (PDF/imagen) + `fecha_vencimiento`, y adjuntos de novedades. Ver `CASOS_DE_USO_MVP2.md`. | — |
| API control de llegadas tarde | Definir fuente: reloj biométrico existente (¿el `ID_HUELLA` que ya está en tu Excel es de un sistema de fichada?), o app de geolocalización, o integración con reloj físico | Definir qué hardware/sistema de fichada tenés hoy |
| Firma digital recibos de sueldo | Servicio de firma (ej. DocuSign/Firmafy) + envío automático por Telegram/mail | Elegir proveedor de firma |
| Envío de datos a tesorería/contable | Export automático (Excel/CSV) de novedades liquidables (faltas, licencias) hacia el sistema contable | Definir qué sistema usa contable (¿Dux también?) |
| Bot de consultas y búsqueda de documentación | Bot Telegram con RAG sobre la documentación cargada del punto 2 | Depende de "Carga de documentación" |

---

## 4. Orden sugerido de implementación

1. Agregar campos faltantes al Excel (vencimientos, teléfono) — 30 min de trabajo.
2. Workflow de alertas diarias (el de mayor impacto inmediato, y usa datos que ya existen en parte).
3. Workflow de antigüedad mensual (simple, dato ya disponible).
4. Definir fuente de asistencia (bloquea 3 métricas + ranking + cross-check de faltas).
5. Dashboard de métricas (una vez que el resto esté alimentando datos reales).
6. MVP2 en el orden de la tabla de arriba, salvo que quieras adelantar la API de asistencia por ser bloqueante.

¿Querés que empecemos agregando las columnas faltantes al `EMPLEADOS.xlsx` y arme el prompt para Claude Code del workflow de alertas diarias?
