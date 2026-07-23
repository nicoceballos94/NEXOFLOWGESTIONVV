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

### E. Ingreso y egreso de personas

**CU-29 — Onboarding (proceso de ingreso)**
Guiar todo el proceso de ingreso de un empleado nuevo con un **checklist** que se
completa paso a paso, para que no quede ningún trámite sin hacer y quede
constancia de quién lo hizo y cuándo.
- *Checklist de ejemplo:*
  - ☐ Alta AFIP/ARCA
  - ☐ Declaración jurada
  - ☐ Uniforme
  - ☐ Email
  - ☐ Usuario ERP
  - ☐ Capacitación
  - ☐ Firma contrato
  - ☐ Foto
  - ☐ Entrega EPP
- *Dos tipos de ítem:* los de **acción** se tildan a mano (uniforme, entrega de
  EPP, alta de usuario ERP); los **documentales** están enlazados a un documento
  del legajo (declaración jurada, firma de contrato, foto). El ítem documental
  **no se tilda por separado**: queda "hecho" cuando ese documento está cargado
  **con el archivo escaneado adjunto**. Así hay una sola fuente de verdad (el
  documento) y el checklist lo refleja, sin dato duplicado que pueda contradecirse.
- *Cómo se usa:* se accede **desde la ficha del empleado** (no es una pantalla
  aparte). Es una tarjeta con barra de avance; los ítems documentales abren el
  mismo "Cargar documento" que ya existe. Al completarse, la tarjeta **colapsa a
  una línea** ("Onboarding completo ✓"), dejando la constancia sin ocupar espacio.
- *Depende de:* el legajo y la documentación del empleado (**ya disponibles desde
  el MVP 1**).
- *Bloqueado por decisión:* no (sí definir el checklist definitivo por empresa —
  Vial Victoria y Premocor pueden diferir, y cuáles ítems son documentales).

**CU-30 — Offboarding (proceso de egreso)**
El espejo del anterior: cuando alguien se va, un **checklist** de baja asegura que
se recupere todo lo entregado y se cierren los trámites, con constancia.
- *Checklist de ejemplo:*
  - ☐ Baja AFIP/ARCA
  - ☐ Devolución notebook
  - ☐ Devolución celular
  - ☐ Uniforme
  - ☐ Llaves
  - ☐ Credencial
  - ☐ Liquidación final
  - ☐ Entrevista de salida
- *Mismo mecanismo que CU-29:* ítems de acción (devolución de notebook, celular,
  llaves, credencial) que se tildan a mano, y documentales enlazados al legajo
  (p. ej. liquidación final) que quedan "hechos" al cargar el documento con su
  archivo adjunto.
- *Cómo se usa:* misma tarjeta en la ficha, que **aparece al usar "Dar de baja"**
  y colapsa al completarse, igual que CU-29.
- *Depende de:* el legajo y la baja lógica (**ya disponible desde el MVP 1**). Se
  dispara al registrar la baja del empleado.
- *Bloqueado por decisión:* no (sí definir el checklist definitivo por empresa).

### F. Configuración y catálogos

**CU-31 — Gestión de tipos de documento desde Configuración**
Que RRHH pueda **agregar y quitar tipos de documento** (carnet, apto médico, CNRT,
declaración jurada…) desde la pantalla de Configuración, sin depender de soporte
técnico. Hoy los tipos se listan para configurar sus días de aviso, pero el alta
de un tipo nuevo solo se hace por herramientas internas.
- *Cómo funciona el "quitar":* es una **baja lógica** (se desactiva el tipo), no
  un borrado físico. Un tipo desactivado desaparece de las pantallas pero **no
  rompe los documentos ya cargados** que lo usan; se puede reactivar.
- *Depende de:* el motor ya existe en el backend (endpoint de tipos de documento
  con alta/baja restringido a Admin/RRHH). Falta **exponerlo en la UI**, junto al
  ABM de empresas y sectores que ya está en Configuración.
- *Bloqueado por decisión:* no — **listo para arrancar** (es trabajo de front).
- *Estado:* ✅ **Hecho (2026-07-23).** ABM en Configuración (alta, edición y baja
  lógica), con el mismo molde que empresas/sectores; verificado contra Postgres.
  Los días de aviso siguen editándose en "Parametría de alertas".
- *Habilita:* los ítems documentales del onboarding/offboarding (CU-29 / CU-30),
  que se enlazan a estos tipos.

---

## 3. Resumen de prioridad y bloqueos

| CU | Ítem | Depende de | ¿Decisión externa pendiente? |
|---|---|---|---|
| CU-25 | Medidas disciplinarias | Nada | No — **listo para arrancar** |
| CU-31 | Tipos de documento en Configuración | Backend ya está (solo UI) | ✅ **Hecho (2026-07-23)** |
| CU-24 | Portal de autogestión | Nada nuevo | No (definir alcance) |
| CU-29 | Onboarding (checklist ingreso) | Legajo (ya está) | No (definir checklist por empresa) |
| CU-30 | Offboarding (checklist egreso) | Legajo/baja (ya está) | No (definir checklist por empresa) |
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
2. Lo que no tiene bloqueos: **CU-25 (disciplina)**, **CU-31 (tipos de documento
   en Configuración, solo front)**, **CU-24 (autogestión)** y **CU-29 / CU-30
   (onboarding / offboarding)**.
3. En cuanto se defina el hardware: **CU-20 → CU-21 → CU-22** (asistencia).
4. Definido el canal: **CU-23 (avisos)** y **CU-28 (bot)**.
5. Con proveedores elegidos: **CU-26 (firma)** y **CU-27 (export contable)**.

---

*Documento orientado al cliente. Para el detalle técnico ver
`DISENO_TECNICO_BACKEND.md` y `MODULO_RRHH_SPEC.md`.*
