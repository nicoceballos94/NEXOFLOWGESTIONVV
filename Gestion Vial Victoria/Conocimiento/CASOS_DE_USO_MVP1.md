# Sistema de RRHH — Casos de uso del MVP 1

> **Para qué sirve este documento:** describir, en lenguaje sencillo, **qué va a poder hacer cada persona** con el sistema en su primera versión (MVP 1). No entra en detalles técnicos: es una guía para acordar con el cliente el alcance y validar que no falte nada importante.
>
> **Empresas del grupo:** Vial Victoria y Premocor. Una misma persona puede haber trabajado en las dos, y el sistema lo tiene en cuenta.

---

## 1. ¿Qué resuelve el sistema en esta primera etapa?

Hoy la información de empleados, licencias y vencimientos vive en planillas de Excel, sueltas y difíciles de controlar. El MVP 1 reemplaza eso por un **sistema único y confiable** que responde tres preguntas de forma inmediata:

1. **¿Quién trabaja con nosotros?** — Legajo ordenado: en qué empresa está cada persona, desde cuándo, con qué documentación al día (carnet, apto médico, CNRT, contrato).
2. **¿Quién está o no está, y por qué?** — Registro claro de faltas, licencias, vacaciones, accidentes y permisos, con su justificación y sus ampliaciones.
3. **¿Qué necesito mirar hoy?** — Avisos de vencimientos, cumpleaños y antigüedad, más reportes de cuánta gente hay, cuántos entran y salen, y cuánto ausentismo tenemos.

> **Nota de alcance:** en esta etapa el control de asistencia por reloj/huella, el cálculo automático de tardanzas y el envío automático de mensajes por WhatsApp **todavía no están activos**. El sistema ya queda preparado para sumarlos más adelante sin rehacer nada.

---

## 2. ¿Quién usa el sistema? (perfiles)

| Perfil | Quién es | Qué hace, en pocas palabras |
|---|---|---|
| **Administrador** | Responsable del sistema | Ve y hace todo; además gestiona usuarios y configuración general. |
| **RRHH** | Equipo de Recursos Humanos | El usuario principal: da de alta empleados, carga documentos, aprueba licencias, mira reportes. Ve a todas las empresas. |
| **Supervisor** | Jefe de sector / obra | Carga novedades de **su equipo** (quedan pendientes de aprobación de RRHH). Ve solo su gente. |
| **Empleado** | El trabajador | Solo consulta lo suyo: sus licencias, sus documentos y vencimientos. En esta etapa no carga nada. |

---

## 3. Casos de uso

Cada caso describe una situación real del día a día y qué hace el sistema.

### A. Gestión de empleados

**CU-01 — Dar de alta un empleado nuevo**
RRHH carga a la persona (nombre, DNI, datos de contacto) y su relación laboral: en qué empresa entra, en qué puesto/sector y desde qué fecha. En un solo paso queda el empleado activo y listo para operar.

**CU-02 — Editar los datos de un empleado**
RRHH corrige o completa datos de una persona ya cargada (teléfono, puesto, sector, etc.).

**CU-03 — Dar de baja a un empleado**
Cuando alguien deja la empresa, RRHH registra la baja con **fecha y motivo de egreso**. El empleado **no se borra**: se conserva todo su historial para poder calcular antigüedad, rotación y, si vuelve, una reincorporación.

**CU-04 — Reincorporar / historial en dos empresas**
Si una persona vuelve a trabajar, o pasa de una empresa del grupo a la otra, el sistema guarda cada etapa como una relación laboral distinta. Así queda claro todo su recorrido sin perder información previa.

**CU-05 — Consultar y buscar empleados**
Cualquier usuario autorizado busca empleados y los filtra por empresa, estado (activo / dado de baja), sector o nombre.

### B. Documentación y vencimientos

**CU-06 — Cargar documentos con fecha de vencimiento**
RRHH registra los documentos de cada empleado (carnet de conducir, apto médico, CNRT, contrato) con su fecha de vencimiento. El objetivo es **evitar irregularidades**: que nadie maneje con el carnet o el apto vencido.

**CU-07 — Ver quién tiene documentación por vencer o vencida**
El sistema muestra un listado de documentos próximos a vencer o ya vencidos, para actuar antes de que sea un problema.

### C. Novedades (ausencias y licencias)

**CU-08 — Cargar una novedad**
Se registra una novedad indicando el tipo (**falta, licencia, vacaciones, accidente, enfermedad, permiso u horas extra**), el motivo y las fechas.
- Si la carga **RRHH**, puede quedar aprobada.
- Si la carga un **Supervisor**, queda **pendiente** hasta que RRHH la apruebe.

**CU-09 — Aprobar o rechazar una novedad**
RRHH revisa las novedades pendientes y las aprueba o rechaza. Solo las novedades **aprobadas** cuentan como justificación válida.

**CU-10 — Prorrogar (ampliar) una licencia**
Cuando una licencia se extiende (ejemplo real: "pie roto" que primero eran 10 días y luego se amplían), se carga una **prórroga** enganchada a la licencia original.
El sistema garantiza que:
- La ampliación sea del **mismo tipo** que la licencia original.
- Las fechas sean **coherentes y continuas** (no se puede "ampliar" dejando un hueco de días en el medio).
- Se pueda ver la **historia completa** de la licencia y sus ampliaciones, sin contradicciones.

**CU-11 — Registrar horas extra**
En esta etapa las horas extra se cargan como una novedad manual: "el empleado X hizo N horas extra" en tal fecha. (El cálculo automático llegará cuando se conecte el reloj de fichaje.)

**CU-12 — Registrar certificado de una novedad**
Para accidentes o enfermedades, RRHH marca si se recibió el certificado y cuándo, para dejar constancia y poder detectar los que faltan.

### D. Avisos y reportes

**CU-13 — Ver los avisos del día**
El sistema arma, para RRHH, los avisos relevantes:
- Cumpleaños del día.
- Documentos por vencer o vencidos (carnet, apto, CNRT, contrato).
- Aniversarios de antigüedad (cumple 1, 2, 3… años).
- Certificados pendientes de entregar.

> En esta etapa los avisos se **consultan dentro del sistema**. El envío automático por WhatsApp queda para una fase siguiente (el sistema ya deja todo listo para conectarlo).

**CU-14 — Reporte de dotación**
Cuánta gente hay activa, cuántos ingresaron y cuántos egresaron en el período, por empresa.

**CU-15 — Reporte de ausentismo**
Total de faltas del período, separadas en justificadas e injustificadas, y promedio por empleado.

**CU-16 — Reporte de rotación**
Índice de rotación del período y principales motivos de egreso, para entender por qué se va la gente.

### E. Confianza y control

**CU-17 — Historial de cambios (auditoría)**
El sistema registra **quién hizo qué y cuándo** sobre la información sensible (altas, bajas, aprobaciones de licencias, prórrogas). Sirve para dar trazabilidad y resolver cualquier duda sobre un cambio.

**CU-18 — Cada uno ve lo que le corresponde**
El acceso está separado por perfil: un supervisor ve solo a su equipo, un empleado solo lo suyo, y los datos sensibles (como el DNI completo) quedan reservados a RRHH y Administración.

**CU-19 — Migrar la información actual desde Excel**
Al arrancar, los datos que hoy están en la planilla de empleados se cargan al sistema en un solo paso, para no tener que reescribir todo a mano y dejar de depender del Excel.

---

## 4. Lo que llega en etapas siguientes (fuera del MVP 1)

Para que quede claro el límite de esta primera versión, esto **no** entra ahora pero está previsto:

- Control de asistencia con **reloj / huella** y cálculo automático de tardanzas y faltas.
- Generación automática de una falta cuando alguien no marca y no tiene licencia que lo justifique.
- **Envío automático de avisos por WhatsApp.**
- Turnos rotativos y su asignación.
- Portal de autogestión para que el empleado cargue o pida cosas por su cuenta.
- Medidas disciplinarias, carga de archivos adjuntos (PDFs) y firma digital de recibos.

---

*Documento orientado al cliente. Para el detalle técnico ver `DISENO_TECNICO_BACKEND.md`.*
