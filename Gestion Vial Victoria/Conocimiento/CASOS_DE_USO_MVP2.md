# Sistema de RRHH — Casos de uso del MVP 2

> **Para qué sirve este documento:** describir, en lenguaje sencillo, **qué va a
> sumar el sistema en su segunda versión (MVP 2)**, partiendo de lo que ya quedó
> funcionando en el MVP 1. No entra en detalle técnico: es la guía para acordar
> el alcance con el cliente y priorizar.
>
> **Fuente:** consolida lo previsto como "etapas siguientes" en
> `CASOS_DE_USO_MVP1.md §4` y el backlog de `MODULO_RRHH_SPEC.md §3`.
>
> **Empresas del grupo:** Vial Victoria y Premocor.

---

## 1. De dónde partimos (qué dejó listo el MVP 1)

El MVP 1 ya reemplaza las planillas de Excel por un sistema único con:

- Legajo de empleados (alta, edición, baja lógica, reingreso, historial en las
  dos empresas) y búsqueda/filtros.
- **Carga de documentación con archivo de respaldo** (carnet, apto médico, CNRT,
  contrato) y control de vencimientos. *(Nota: en el backlog original figuraba
  como MVP 2 sobre Google Drive; se hizo antes, con almacenamiento propio.)*
- Novedades (faltas, licencias, vacaciones, accidentes, permisos, horas extra),
  con aprobación, prórrogas y adjuntos de certificados.
- Avisos del día, reportes de dotación / ausentismo / rotación.
- Acceso por rol y login por usuario.

### Arrastre del MVP 1 (conviene cerrarlo al arrancar el MVP 2)

Dos casos de uso del MVP 1 quedaron pendientes y son la mejor puerta de entrada
al MVP 2:

- **CU-19 — Migrar la información actual desde Excel.** Sin la carga inicial de
  datos reales, varias métricas y automatismos del MVP 2 no tienen con qué
  trabajar. **Recomendado hacerlo primero.**
- **CU-17 — Historial de cambios (auditoría) consultable.** Hoy se registra
  quién creó cada dato; falta el registro consultable de quién aprobó, dio de
  baja o prorrogó, y una pantalla para verlo. Puede ir en paralelo, no bloquea.

---

## 2. Casos de uso del MVP 2

Cada caso indica **qué resuelve**, **de qué depende** y si está **bloqueado por
una decisión externa** que hay que tomar antes de programarlo.

### A. Asistencia y automatismos

**CU-20 — Control de asistencia (fichada)**
Conectar la fuente de fichada para saber quién llegó, quién llegó tarde y quién
no vino, sin cargarlo a mano.
- *Depende de:* definir la fuente (reloj biométrico/huella existente — ¿el
  `ID_HUELLA` del Excel?, app de geolocalización, o reloj físico con API/export).
- *Bloqueado por decisión:* **sí** — qué hardware/sistema de fichada hay hoy.
- *Impacto:* alto. Desbloquea el ausentismo real, el ranking de puntualidad y el
  cross-check de faltas. La spec lo marca como el ítem bloqueante clave.

**CU-21 — Generación automática de faltas y tardanzas**
Cuando alguien no marca y no tiene una licencia que lo justifique, el sistema
genera la falta solo; ídem las tardanzas a partir de la hora de fichada.
- *Depende de:* **CU-20**.
- *Bloqueado por decisión:* hereda el de CU-20.

**CU-22 — Turnos rotativos y su asignación**
Definir turnos y asignarlos a la gente, para que la asistencia se evalúe contra
el turno correcto (no contra un horario fijo).
- *Depende de:* CU-20 para que aporte valor real (se puede modelar antes).
- *Bloqueado por decisión:* no.

### B. Comunicación con el empleado

**CU-23 — Avisos automáticos al empleado**
Hoy los avisos (vencimientos, cumpleaños, certificados pendientes) se
**consultan** dentro del sistema. Este CU los **empuja** al empleado por un canal.
- *Depende de:* teléfono/contacto cargado.
- *Bloqueado por decisión:* **sí** — elegir canal: **WhatsApp** (lo menciona el
  doc de casos de uso; requiere API de WhatsApp Business), **Telegram** (lo
  menciona la spec, más simple y encaja con el bot del CU-27) o **email**.

**CU-24 — Portal de autogestión del empleado**
Que el empleado pueda pedir/cargar cosas por su cuenta (p. ej. solicitar una
licencia o ver sus recibos), y no solo consultar lo suyo.
- *Depende de:* nada nuevo del lado de datos.
- *Bloqueado por decisión:* no (sí definir el alcance: cuánto puede autogestionar).

### C. Disciplina y liquidación

**CU-25 — Medidas disciplinarias**
Registrar apercibimientos y suspensiones ligados a la persona, con motivo y
fecha, para tener el historial disciplinario ordenado.
- *Depende de:* nada — **se puede construir ya**.
- *Bloqueado por decisión:* no.

**CU-26 — Firma digital de recibos de sueldo**
Enviar el recibo y recibir la conformidad firmada del empleado, con constancia.
- *Depende de:* elegir proveedor de firma (p. ej. DocuSign / Firmafy) + canal de
  envío.
- *Bloqueado por decisión:* **sí** — proveedor de firma.

**CU-27 — Export a tesorería / contable**
Exportar automáticamente las novedades liquidables (faltas, licencias) al sistema
contable, en lugar de rehacerlas a mano.
- *Depende de:* saber qué sistema usa contable y en qué formato lo espera.
- *Bloqueado por decisión:* **sí** — sistema contable de destino (¿Dux?).

### D. Consultas asistidas

**CU-28 — Bot de consultas y búsqueda de documentación**
Un bot (p. ej. Telegram) que responda consultas y busque sobre la documentación
cargada, usando RAG.
- *Depende de:* la documentación cargada (**ya disponible desde el MVP 1**).
- *Bloqueado por decisión:* no (encaja con el canal que se elija en CU-23).

---

## 3. Resumen de prioridad y bloqueos

| CU | Ítem | Depende de | ¿Decisión externa pendiente? |
|---|---|---|---|
| CU-25 | Medidas disciplinarias | Nada | No — **listo para arrancar** |
| CU-24 | Portal de autogestión | Nada nuevo | No (definir alcance) |
| CU-28 | Bot de consultas (RAG) | Documentación (ya está) | No |
| CU-20 | Asistencia / fichada | Fuente de fichada | **Sí** — qué hardware hay hoy |
| CU-21 | Faltas/tardanzas automáticas | CU-20 | Hereda de CU-20 |
| CU-22 | Turnos rotativos | CU-20 (para valor real) | No |
| CU-23 | Avisos automáticos | Contacto cargado | **Sí** — canal (WhatsApp/Telegram/email) |
| CU-26 | Firma digital de recibos | Proveedor de firma | **Sí** — proveedor |
| CU-27 | Export a contable | Sistema contable destino | **Sí** — qué sistema/formato |

### Decisiones a cerrar antes de programar

1. **Fichada (CU-20):** ¿qué sistema de asistencia existe hoy? (el `ID_HUELLA`
   del Excel sugiere un reloj biométrico) → es la decisión de mayor impacto.
2. **Canal de avisos (CU-23):** WhatsApp, Telegram o email.
3. **Proveedor de firma (CU-26)** y **sistema contable destino (CU-27)**.

### Orden sugerido

1. Cerrar el arrastre del MVP 1: **CU-19 (importar Excel)** primero, **CU-17
   (auditoría)** en paralelo.
2. Lo que no tiene bloqueos: **CU-25 (disciplina)** y **CU-24 (autogestión)**.
3. En cuanto se defina el hardware: **CU-20 → CU-21 → CU-22** (asistencia).
4. Definido el canal: **CU-23 (avisos)** y **CU-28 (bot)**.
5. Con proveedores elegidos: **CU-26 (firma)** y **CU-27 (export contable)**.

---

*Documento orientado al cliente. Para el detalle técnico ver
`DISENO_TECNICO_BACKEND.md` y `MODULO_RRHH_SPEC.md`.*
