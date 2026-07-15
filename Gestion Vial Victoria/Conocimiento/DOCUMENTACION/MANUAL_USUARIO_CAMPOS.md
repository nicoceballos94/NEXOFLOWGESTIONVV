# Manual de usuario — Empleados y Novedades

**Sistema de Gestión RRHH · Grupo Vial Victoria / Premocor**
**Versión:** MVP 1 · **Fecha:** 15 de julio de 2026 · rama `fase-0-verificada`

---

## Para qué sirve este manual

Este documento explica **campo por campo** qué se carga en el sistema, quién lo carga,
qué reglas lo gobiernan y —lo más importante— **para qué se usa cada dato**.

Está escrito para tres lecturas distintas:

- **RRHH y supervisores** (uso diario): las secciones 3, 4, 5 y 6 son el instructivo de
  carga. Qué significa cada campo y qué pasa si lo dejo vacío.
- **Dirección** (uso analítico): la sección 7 explica exactamente cómo se calcula cada
  métrica del panel. Un número solo sirve si se sabe qué mide.
- **Decisión de producto**: la sección 8 es la más importante y la más incómoda. Lista
  los campos que **hoy se cargan pero no alimentan ninguna métrica**, y separa los que
  tienen valor dormido de los que probablemente sean lastre.

> **Cómo se hizo:** todo lo que sigue está verificado contra el código real del repositorio
> (modelos, servicios, selectores y la capa de integración del frontend), no contra el
> diseño ni contra la intención. Cuando el manual dice "no se usa", significa que se buscó
> en el código y no existe la consulta que lo usaría.

---

## 1. Cómo leer este manual

En las tablas de campos se usan estas convenciones:

| Marca | Significado |
|---|---|
| **Obligatorio** | El sistema no deja guardar sin este dato. |
| **Opcional** | Se puede guardar vacío. Ojo: "opcional" no es "irrelevante" (ver sección 8). |
| **Automático** | Lo calcula o lo asigna el sistema; el usuario no lo escribe. |
| **Único** | No puede repetirse entre empleados. El sistema rechaza el duplicado. |
| 📊 | El campo **alimenta una métrica hoy**. |
| 💤 | El campo **se carga pero no alimenta ninguna métrica** (ver sección 8). |
| 🔒 | Campo **reservado a una fase futura**; hoy es solo dato guardado. |

---

## 2. Conceptos base (el modelo mental)

Antes de los campos hay que entender tres decisiones de diseño. Sin esto, media
documentación no se entiende.

### 2.1 La persona y el vínculo son cosas distintas

El sistema separa **Empleado** (la persona) de **Relación laboral** (su vínculo con una
empresa del grupo).

- El **Empleado** es único en todo el grupo: un DNI, una ficha. Lleva los datos que
  pertenecen a la persona y no cambian si cambia de empresa: nombre, DNI, teléfono,
  obra social, contacto de emergencia.
- La **Relación laboral** es el vínculo con **una** empresa: desde cuándo, en qué puesto,
  con qué contrato, y —si terminó— cuándo y por qué.

Una misma persona puede tener **varias relaciones a lo largo del tiempo**: entró a Vial
Victoria en 2019, se fue en 2022, volvió en 2024 a Premocor. Son tres etapas, tres
registros, un solo legajo. Esto es lo que permite reconstruir historia real en vez de
pisarla.

> **Regla dura:** una persona puede tener **una sola relación ACTIVA por empresa** a la
> vez. La base de datos lo impide, no solo la pantalla.

### 2.2 Nadie se borra

Dar de baja a alguien **no borra nada**. Se cierra la relación laboral con fecha y motivo
de egreso, y el historial queda intacto. Esto no es prolijidad: es la condición para poder
calcular antigüedad, rotación y reingresos. Un sistema que borra no puede medir.

### 2.3 La licencia que se extiende es una cadena, no un campo editable

Cuando una licencia se prorroga (el caso clásico: "pie roto, 10 días" que después son 25),
el sistema **no edita la fecha de fin original**. Crea un registro nuevo —una **prórroga**—
enganchado a la licencia original (la "madre").

La vigencia total de la licencia es un **dato calculado** en el momento: desde el inicio de
la madre hasta la última fecha de fin aprobada de la cadena. Nunca se guarda como campo.

**Por qué importa:** si la vigencia fuera un campo editable, tarde o temprano diría algo
distinto de lo que dicen las prórrogas cargadas, y no habría forma de saber cuál miente.
Al calcularla, no puede contradecirse. El costo es que hay que entender el concepto de
cadena; el beneficio es que el dato nunca está mal.

---

## 3. Módulo Empleado — diccionario de campos

### 3.1 Identificación

| Campo | Qué es | Estado | Reglas y detalles |
|---|---|---|---|
| **Legajo** | Número de orden de la persona en el grupo. | Automático · Único | Lo asigna el sistema (0001, 0002, …). **No se carga a mano**: es un número de la organización, no un dato de la persona. Dos altas simultáneas nunca reciben el mismo número. |
| **DNI** | Documento de identidad. | **Obligatorio** · Único | Es la identidad real de la persona en el sistema. Si ya existe, el alta se rechaza: esa persona ya está cargada (quizá dada de baja — corresponde reingreso, no alta nueva). |
| **CUIL** | Clave laboral. | Opcional · Único | 💤 Hoy es solo dato de ficha. Es la llave natural para cruzar con liquidación de sueldos o AFIP el día que se integre. |
| **Nombre** | Nombre de pila. | **Obligatorio** | |
| **Apellido** | Apellido. | **Obligatorio** | Ordena todos los listados. |

### 3.2 Datos personales y contacto

| Campo | Qué es | Estado | Reglas y detalles |
|---|---|---|---|
| **Fecha de nacimiento** | — | Opcional | 💤 No alimenta ninguna métrica hoy, **pero es el campo con más valor dormido del sistema** (ver §8.1): avisos de cumpleaños y pirámide etaria dependen de él. |
| **Teléfono** | Contacto directo. | Opcional | Operativo. |
| **Email** | Correo. | Opcional | 💤 Operativo hoy. Es el canal natural de los avisos automáticos cuando se activen. |
| **Dirección** | Domicilio. | Opcional | 💤 Texto libre: sirve para buscar a la persona, no para analizar (ver §8.3). |
| **Educación** | Nivel educativo alcanzado. | Opcional | 💤 Lista cerrada: Primario incompleto/completo, Secundario incompleto/completo, Terciario, Universitario. Al ser lista cerrada **sí es agregable** — hoy nadie lo agrega. |
| **Contacto de emergencia** | A quién llamar. | Opcional | 💤 Un **único campo de texto** con nombre, vínculo y teléfono juntos (ej. "María Pérez · esposa · 351-555-1234"). Decisión consciente del MVP. Nunca será una métrica; es información crítica en el peor momento. |
| **Observaciones** | Notas libres. | Opcional | 💤 Texto libre, no agregable por definición. |

### 3.3 Salud y seguridad

| Campo | Qué es | Estado | Reglas y detalles |
|---|---|---|---|
| **Obra social** | Cobertura médica. | Opcional | 💤 Texto libre. Ver §8.3: debería ser catálogo. |
| **ART** | Aseguradora de riesgos del trabajo. | Opcional | 💤 Texto libre. Cruzado con las novedades de tipo Accidente daría siniestralidad por aseguradora — hoy imposible de agregar por ser texto libre. |

### 3.4 Acceso y biometría

| Campo | Qué es | Estado | Reglas y detalles |
|---|---|---|---|
| **ID de huella** | Identificador biométrico (ej. HUELLA-0042). | Opcional · Único | 🔒 **Reservado a la fase de asistencias.** Se carga desde ahora, a propósito: cuando se conecte el reloj de fichaje, el matching necesita este dato ya poblado. Hoy no hace nada. Esto es previsión, no campo muerto. |
| **Exento de marcación** | Si la persona no marca reloj. | Opcional (No por defecto) | 🔒 Reservado a la fase de asistencias, misma lógica que el anterior. |
| **Usuario del sistema** | Cuenta de acceso, si la tiene. | Opcional | 💤 Solo para quien entra al sistema. La mayoría de los empleados no tiene. |

### 3.5 Relación laboral (el vínculo con la empresa)

Estos campos **no están en la persona**: están en cada etapa laboral. Una persona con tres
etapas tiene tres juegos de estos datos.

| Campo | Qué es | Estado | Reglas y detalles |
|---|---|---|---|
| **Empresa** | Vial Victoria o Premocor. | **Obligatorio** | 📊 **No se edita nunca.** Cambiar de empresa es dar de baja en una y reingresar en la otra: son dos etapas distintas de la historia laboral, no una corrección. |
| **Fecha de ingreso** | Inicio del vínculo. | **Obligatorio** | 📊 **El campo más cargado de consecuencias del sistema.** Es la base de la antigüedad, de los ingresos del mes y de la rotación. Un error acá desplaza tres métricas. |
| **Sector** | RRHH, Administración, Obra, Logística… | Opcional | 💤 Transversal al grupo (los sectores no se duplican por empresa). Se puede filtrar por sector, pero **ninguna métrica se abre por sector** (ver §8.1 — es el hueco analítico más grande). |
| **Puesto** | Cargo. | Opcional | 💤 Mismo caso que Sector. |
| **Jornada legal** | Completa (8h), Reducida (6h), Media (4h) o Rotativa. | Opcional | 💤 Lista cerrada, agregable, sin usar. Es lo que permitiría medir dotación equivalente en vez de contar cabezas. |
| **Tipo de contrato** | Indeterminado, Plazo fijo, Eventual, Temporada, Pasantía. | Opcional (Indeterminado por defecto) | 💤 Lista cerrada, agregable, sin usar. |
| **Vencimiento de contrato** | Fin previsto del contrato. | Opcional | 💤 **Hueco operativo, no solo analítico.** El sistema guarda la fecha pero **no avisa nada** cuando se acerca. Un plazo fijo puede vencer sin que nadie se entere (ver §8.1). |
| **Estado** | Activa o Finalizada. | Automático | 📊 Lo mueve la baja, no se edita a mano. Es la fuente de verdad del KPI de empleados activos. |
| **Fecha de egreso** | Cuándo terminó. | Automático (en la baja) | 📊 Alimenta egresos del mes y rotación. No puede ser anterior al ingreso. |
| **Motivo de egreso** | Renuncia, Fin de contrato, Despido, Jubilación, Mudanza, Otro. | Automático (en la baja) | 💤 **Se pide en cada baja y no se usa para nada.** Lista cerrada, perfectamente agregable. Ver §8.1: separa rotación voluntaria de involuntaria, que son dos problemas distintos con dos soluciones distintas. |
| **Antigüedad** | Días desde el ingreso. | Automático | 💤 Se calcula al vuelo (hasta hoy, o hasta el egreso si terminó). Se muestra en la ficha; **ninguna métrica la agrega**. |

### 3.6 Documentos del empleado

| Campo | Qué es | Estado | Reglas y detalles |
|---|---|---|---|
| **Tipo de documento** | Carnet, apto médico, CNRT, contrato… | **Obligatorio** | Catálogo administrable. **Un solo documento vigente por tipo y por persona**: renovar el apto médico es mover su fecha de vencimiento, no cargar otro. |
| **Número** | Número o identificación. | Opcional | 💤 |
| **Fecha de vencimiento** | Cuándo caduca. | Opcional | 💤 **Ver §8.1 — el hueco más caro del sistema.** La ficha del empleado pinta el documento en rojo (vencido) o amarillo (vence en ≤30 días), **pero solo si alguien abre esa ficha**. No existe el listado "quién tiene documentación por vencer". |
| **Observaciones** | Notas. | Opcional | 💤 |

> **Nota:** un documento cargado por error **sí se puede borrar** (a diferencia de la
> relación laboral). Un error de carga no es un hecho de la historia laboral que valga la
> pena preservar. Al renovar un vencimiento no queda historial de la versión anterior:
> es una decisión consciente del MVP, a revisar cuando se suban archivos adjuntos.

---

## 4. Casos de uso — Empleado

### CU-01 · Alta de un empleado nuevo

**Quién:** RRHH o Administrador.
**Cuándo:** entra una persona que nunca trabajó en el grupo.

RRHH carga en un solo paso los datos de la persona **y** su primera relación laboral
(empresa, fecha de ingreso, y opcionalmente sector, puesto, jornada y contrato). El
sistema asigna el legajo y la persona queda activa.

**Lo que el sistema garantiza:** o se crean la persona y la relación, o no se crea nada.
Nunca queda una persona sin vínculo, huérfana en el listado.

**Errores frecuentes:**
- *"El DNI ya existe"* → la persona ya está en el sistema, probablemente dada de baja.
  Corresponde **CU-04 (reingreso)**, no un alta nueva.
- Cargar el legajo a mano: no se puede, y está bien que así sea.

### CU-02 · Editar la ficha de un empleado

**Quién:** RRHH o Administrador.

Se corrigen datos de la persona (teléfono, obra social, educación…). **La empresa no se
edita**: si la persona pasó de Vial Victoria a Premocor, eso es baja + reingreso (CU-04),
porque son dos etapas distintas de su historia.

### CU-03 · Dar de baja

**Quién:** RRHH o Administrador.
**Cuándo:** la persona deja la empresa.

Se registra **fecha de egreso** y **motivo de egreso**. La relación pasa a Finalizada; la
persona y todo su historial se conservan.

**Lo que el sistema garantiza:** la fecha de egreso no puede ser anterior al ingreso.
Una relación ya finalizada no se vuelve a finalizar.

**Efecto inmediato:** el empleado sale del KPI de activos y suma a los egresos del mes y
a la rotación. **No se pueden cargar novedades nuevas** sobre alguien dado de baja (las
históricas quedan).

### CU-04 · Reingreso o pase entre empresas

**Quién:** RRHH o Administrador.

La persona ya existe (mismo DNI, mismo legajo). Se le agrega una **relación laboral
nueva** con la empresa y fecha de ingreso correspondientes. El sistema exige que no
tenga otra relación activa en esa misma empresa.

**Por qué así:** el recorrido completo queda visible —2019-2022 Vial Victoria,
2024-hoy Premocor— y cada etapa mantiene su antigüedad y su motivo de salida. Editar la
relación vieja habría borrado la historia.

### CU-05 · Buscar y filtrar empleados

**Quién:** cualquier usuario autorizado.

Búsqueda por nombre, apellido, legajo o DNI; filtros por empresa, sector y estado
(activo / dado de baja).

**Detalle importante:** los filtros de empresa, sector y estado se aplican **sobre la
misma relación laboral**. Filtrar "Premocor + Activo" trae quien está activo *en
Premocor* — no quien está activo en Vial Victoria y alguna vez pasó por Premocor.

### CU-06 · Cargar documentación

**Quién:** RRHH.

Se registra cada documento con su vencimiento. Un vigente por tipo. Renovar = mover la
fecha de vencimiento del documento existente.

### CU-07 · Ver documentación por vencer ⚠️ **parcialmente implementado**

Este caso de uso **está en el alcance acordado pero hoy funciona a medias**: la ficha de
cada empleado pinta sus documentos (rojo = vencido, amarillo = vence dentro de 30 días),
pero **no existe la vista que cruce a toda la dotación**. Para saber quiénes tienen el
apto médico por vencer hay que abrir las fichas de a una.

Ver §8.1: es el hueco más caro del sistema y el más barato de cerrar.

---

## 5. Módulo Novedades — diccionario de campos

### 5.1 El catálogo de tipos y sus comportamientos

Cada tipo de novedad trae **cuatro interruptores** que definen cómo se comporta. No son
decoración: gobiernan las reglas.

| Tipo | Justifica ausencia | Ocupa el día | Pide certificado | Admite prórroga |
|---|:---:|:---:|:---:|:---:|
| **Falta** | ✗ | ✓ | ✗ | ✗ |
| **Licencia médica** | ✓ | ✓ | ✓ | ✓ |
| **Accidente / ART** | ✓ | ✓ | ✓ | ✓ |
| **Vacaciones** | ✓ | ✓ | ✗ | ✗ |
| **Permiso** | ✓ | ✓ | ✗ | ✗ |
| **Horas extra** | ✗ | ✗ | ✗ | ✗ |

**Justifica ausencia** y **ocupa el día** se confunden todo el tiempo y son cosas distintas:

- **Falta**: *ocupa* el día (nadie falta y está de licencia el mismo día) pero **no lo
  justifica** — es exactamente lo que la falta significa.
- **Horas extra**: es el único tipo que **no ocupa** el día. Se pueden hacer horas extra
  el mismo día que hay cualquier otra cosa. Por eso conviven.

### 5.2 Campos de una novedad

| Campo | Qué es | Estado | Reglas y detalles |
|---|---|---|---|
| **Empleado** | De quién es. | **Obligatorio** | 📊 No se puede cargar sobre alguien dado de baja. |
| **Tipo** | Falta, licencia, vacaciones… | **Obligatorio** | 📊 Define todo el comportamiento (§5.1). Determina si cuenta como ausentismo. |
| **Fecha desde** | Inicio. | **Obligatorio** | 📊 Es la fecha por la que la novedad **cae dentro de un mes** en todas las métricas. |
| **Fecha hasta** | Fin. | Opcional | 📊 **Vacío = novedad abierta**, y es un significado real, no un olvido: la licencia sin alta médica corre sin fecha de fin y bloquea el calendario hacia adelante hasta que se cierre. |
| **Días** | Atajo de carga. | Alternativa | El formulario acepta "fecha + N días" y calcula la fecha de fin. No es un campo guardado. |
| **Estado** | Dónde está en el circuito. | Automático | 📊 Se mueve con acciones (aprobar/rechazar/anular), **nunca editando**. |
| **Clasificación** | Justificada / Injustificada. | Opcional | 💤 **Se carga y no se usa.** Ver §8.1: es la línea entre "el ausentismo que se gestiona" y "el ausentismo que se sanciona", y hoy el panel las suma juntas. |
| **Motivo** | Texto corto. | Opcional | 💤 Texto libre. Se puede buscar, no agregar. |
| **Observaciones** | Notas largas. | Opcional | 💤 Acá se acumulan automáticamente los motivos de rechazo y anulación. |
| **Fecha de aviso del empleado** | Cuándo avisó la persona. | Opcional | 💤 Comparado con la fecha de inicio da **avisos tardíos** — un indicador de cultura de trabajo que hoy nadie mira (§8.1). |
| **Requiere praxis** | Hay intervención de ART / seguimiento médico. | Opcional | 💤 Se marca solo si se carga una fecha de turno. |
| **Fecha de turno de praxis** | Turno médico. | Opcional | 💤 |
| **Fecha de fin estimada** | Cuándo se preveía el alta. | Opcional | 💤 Contra la fecha de fin real mide **cuánto se desvían las licencias de lo previsto** (§8.2). |
| **Fecha de reintegro** | Vuelta efectiva. | Opcional | 💤 |
| **Certificado recibido el** | Cuándo se presentó. | Opcional | 💤 **Se carga y no se usa.** Los tipos con "pide certificado" deberían disparar una alerta si pasa el plazo; esa alerta **no existe** (§8.1). |
| **Cantidad de horas** | Horas extra. | Condicional | 💤 **Obligatorio** solo para Horas extra; el sistema lo exige. Y no hay ninguna métrica de horas extra (§8.1). |
| **Novedad origen** | A qué licencia madre pertenece. | Automático | 📊 Lo pone el sistema al prorrogar. Apunta **siempre a la madre**, nunca a la prórroga anterior: la cadena es plana. Evita el doble conteo en las métricas. |
| **Relación laboral** | Contexto de empresa/contrato. | Automático | 📊 Por defecto, la relación activa del empleado. Es lo que le da empresa a la novedad. |
| **Generada automáticamente** | Si la creó un proceso. | Automático | 🔒 Hoy siempre "no": distingue la carga manual del cruce automático con el reloj de fichaje, que todavía no existe. |
| **Aprobada por / Aprobada el** | Quién y cuándo aprobó. | Automático | 💤 Se registra en cada aprobación y **no se usa**. Es el insumo del tiempo de aprobación (§8.2). |

### 5.3 Los estados y qué significan

| Estado | Qué significa | ¿Ocupa el calendario? | ¿Cuenta en métricas? |
|---|---|:---:|:---:|
| **Registrada** | Cargada, esperando resolución. Es el "Pendiente" de la pantalla. | ✓ | ✓ |
| **En proceso** | En revisión. | ✓ | ✓ |
| **Aprobada** | Validada. **Solo estas justifican de verdad.** | ✓ | ✓ |
| **Rechazada** | No se aceptó: nunca pasó. | ✗ | ✗ |
| **Cerrada** | Ya transcurrió y terminó. | ✓ | ✓ |
| **Anulada** | Se borra de los hechos (error de carga). | ✗ | ✗ |

**La lógica detrás:** solo **Rechazada** y **Anulada** liberan las fechas del empleado. Una
**Cerrada** ya ocurrió — sigue ocupando su período y nada puede pisarla. Rechazar o anular
la novedad vieja es, entonces, la forma de liberar fechas para cargar otra cosa.

---

## 6. Casos de uso — Novedades

### CU-08 · Cargar una novedad

**Quién:** RRHH (puede aprobarla) o Supervisor (queda pendiente de RRHH).

Se elige empleado, tipo, fechas y motivo. La novedad nace **Registrada**.

**Lo que el sistema garantiza — la regla de no solapamiento:**
un empleado **no puede tener dos novedades en las mismas fechas**. Si ya tiene vacaciones
del 10 al 20 y se intenta cargar una licencia del 15 al 18, el sistema lo rechaza
diciendo exactamente qué novedad está en el camino y en qué estado. Las horas extra son
la excepción: conviven con lo que haya.

> **Detalle técnico que vale conocer:** esta regla está protegida **dos veces** — con un
> mensaje amigable en la aplicación y con una restricción en la base de datos. La primera
> explica; la segunda es infalible incluso si dos personas cargan al mismo tiempo. Es una
> regla que no se puede violar ni por accidente ni por concurrencia.

**Errores frecuentes:**
- *"El empleado ya tiene una novedad en ese período"* → corregir las fechas, o rechazar/
  anular la anterior si estaba mal.
- *"No se pueden registrar novedades de un empleado dado de baja"* → si volvió, primero el
  reingreso (CU-04).

### CU-09 · Aprobar o rechazar

**Quién:** solo RRHH o Administrador.

Se resuelve una novedad Registrada o En proceso. Al aprobar quedan registrados **quién** y
**cuándo**. Al rechazar se puede dejar un motivo, que se acumula en las observaciones.

Una novedad ya resuelta **no se vuelve a resolver**, y solo se puede **editar mientras
está Registrada**: una vez en proceso o resuelta, es inmutable. Para corregir algo ya
aprobado hay que anularlo y cargarlo bien.

### CU-10 · Prorrogar una licencia

**Quién:** RRHH.
**Cuándo:** la licencia se extiende (el "pie roto" que de 10 días pasa a 25).

Se indica solo la **nueva fecha de fin**. El sistema hace el resto:

1. Encuentra la licencia madre (aunque se haya hecho clic sobre una prórroga).
2. Calcula el inicio de la prórroga: **el día siguiente** al fin de la vigencia actual —
   nunca hay huecos ni superposición.
3. Hereda el tipo de la madre.
4. La prórroga nace **Registrada**: se aprueba como cualquier otra.

**Lo que el sistema garantiza:**
- Solo se prorroga una licencia **aprobada** y de un tipo que **admita prórroga**
  (licencia médica y accidente; vacaciones no se prorrogan).
- La nueva fecha debe ser **posterior** a la vigencia actual: una "prórroga" que no
  extiende nada se rechaza.
- **Una prórroga pendiente por vez.** Si hay una sin aprobar, hay que resolverla antes de
  volver a prorrogar — de lo contrario se crearían dos eslabones pisados sobre las mismas
  fechas.
- Una licencia sin fecha de fin (abierta) **no se puede prorrogar**: no hay desde dónde
  extender. Primero se le pone fin.

**Anulaciones:** anular una prórroga no toca el resto de la cadena. Anular la **madre**
teniendo prórrogas activas **está bloqueado** — hay que anular cada prórroga primero, para
que nadie deje eslabones colgando de una licencia que ya no existe.

### CU-11 · Registrar horas extra

**Quién:** RRHH o Supervisor.

Se carga como novedad de tipo Horas extra con **cantidad de horas obligatoria**. Conviven
con cualquier otra novedad del mismo día. El cálculo automático llegará con el reloj de
fichaje.

---

## 7. Métricas que produce el sistema hoy

Todas se calculan **en el momento de mirarlas**, directo contra la base. No hay valores
guardados que puedan quedar desactualizados ni procesos nocturnos que puedan fallar en
silencio.

### 7.1 Las métricas, con su definición exacta

| Métrica | Qué mide exactamente | Campos que la alimentan |
|---|---|---|
| **Empleados activos** | Personas con al menos una relación en estado **Activa** hoy. Se cuenta la **persona**, no la relación: quien tiene dos vínculos no cuenta doble. | Relación: `estado` |
| **Variación de activos** | Diferencia contra el cierre del mes anterior, reconstruido **por fechas** de ingreso/egreso. | Relación: `fecha_ingreso`, `fecha_egreso` |
| **Ingresos del mes** | Relaciones que **empiezan** dentro del mes calendario. Un reingreso cuenta como ingreso — correcto: es una incorporación real. | Relación: `fecha_ingreso` |
| **Egresos del mes** | Relaciones que **terminan** dentro del mes calendario. | Relación: `fecha_egreso` |
| **Ausentismo del mes** | **Cantidad de novedades** (no de días) de tipo **Falta, Licencia médica o Accidente** que empiezan en el mes. Excluye anuladas y rechazadas. Cuenta solo las madres: una licencia con 3 prórrogas es **un** evento. | Novedad: `tipo`, `fecha_desde`, `estado`, `novedad_origen` |
| **Índice de rotación** | `((ingresos + egresos) / 2) ÷ dotación promedio × 100`. Fórmula estándar. Disponible mensual y anual (12 meses), con serie para el gráfico. | Relación: `fecha_ingreso`, `fecha_egreso` |
| **Ranking de faltas** | Top 5 empleados por **días de falta** del mes (ambos extremos inclusive). Acá sí se cuentan **días**, no eventos. | Novedad: `tipo`, `fecha_desde`, `fecha_hasta`, `empleado` · Relación: `empresa` |

> ⚠️ **Advertencia de lectura — "Ausentismo del mes" mide eventos, no días.** Una licencia
> de 30 días y un permiso de 2 horas suman **1 cada uno**. Es un contador de episodios,
> no de tiempo perdido. Para volumen de ausentismo real hay que mirar el ranking de faltas
> (que sí cuenta días) o construir la métrica de días que falta (§8.1). **No es un
> porcentaje de ausentismo** en el sentido clásico y no debería leerse como tal.

> **Un detalle fino, deliberado:** el KPI de activos usa el **estado** de la relación,
> mientras que la variación y la rotación usan las **fechas**. No es una inconsistencia:
> el KPI tiene que coincidir con lo que muestra el listado de empleados (si RRHH dio de
> baja a alguien con egreso futuro, ya no está activo), mientras que la reconstrucción
> histórica necesita las fechas para poder mirar hacia atrás.

### 7.2 Mapa rápido: campo → métrica

**Campos que trabajan (7 de los ~45 que se cargan):**

| Campo | Alimenta |
|---|---|
| Relación · `fecha_ingreso` | Activos · Variación · Ingresos · **Rotación** · Antigüedad |
| Relación · `fecha_egreso` | Variación · Egresos · **Rotación** |
| Relación · `estado` | Activos |
| Relación · `empresa` | Ranking de faltas (etiqueta) |
| Novedad · `tipo` | Ausentismo · Ranking |
| Novedad · `fecha_desde` | Ausentismo · Ranking |
| Novedad · `fecha_hasta` | Ranking (días) |
| Novedad · `estado` | Ausentismo · Ranking (exclusión) |
| Novedad · `novedad_origen` | Ausentismo (evita doble conteo) |

**La conclusión incómoda:** el sistema captura del orden de **45 campos** y las métricas
usan **9**. Todo lo demás es ficha, operación o potencial dormido. La sección siguiente
es sobre eso.

---

## 8. Campos que se cargan y no se usan

Esta sección responde la pregunta central: *¿qué estamos pidiendo que se cargue, para qué
podría servir, y qué deberíamos dejar de pedir?*

Un campo que se carga y nunca se lee tiene un costo real: tiempo de carga, formulario más
largo, y —lo peor— genera la ilusión de que el dato está bajo control. Vale la pena
mirarlos de frente.

### 8.1 Alto potencial — métricas al alcance de la mano

Estos campos **ya se cargan y ya tienen los datos**. Lo único que falta es la consulta que
los lea. Ordenados por relación valor/esfuerzo:

| # | Campo | Métrica que habilita | Por qué importa |
|:--:|---|---|---|
| **1** | Documentos · `fecha_vencimiento` | **Alerta de vencimientos de toda la dotación** | 🔴 **El hueco más caro.** El dato está cargado y hasta indexado en la base *específicamente para esta consulta* — la consulta nunca se escribió. Hoy solo se ve documento por documento abriendo cada ficha. El objetivo declarado del sistema es "que nadie maneje con el carnet vencido", y eso hoy depende de que alguien se acuerde de mirar. **El umbral de 30 días está fijo en el código**, cuando ya existe una tabla de parámetros pensada para configurarlo. |
| **2** | Novedad · `clasificacion` | **Ausentismo justificado vs. injustificado** | 🔴 Se pide en cada carga y no se lee nunca. Son dos fenómenos distintos: el justificado se gestiona, el injustificado se sanciona. Sumarlos juntos, como hace el panel hoy, **oculta el único ausentismo sobre el que se puede accionar**. |
| **3** | Relación · `motivo_egreso` | **Rotación voluntaria vs. involuntaria** | 🔴 Es la métrica estándar de RRHH y el sistema tiene el dato en cada baja. Un 15% de rotación por renuncias (la gente se va) y un 15% por despidos (la empresa saca) exigen decisiones opuestas — el índice actual los suma y no distingue. |
| **4** | Relación · `sector` y `puesto` | **Abrir todas las métricas por sector** | 🔴 Se puede *filtrar* por sector pero ninguna métrica se *abre* por sector. "12% de ausentismo" no dice nada accionable; "30% en Obra y 3% en Administración" señala dónde está el problema. El dato está: falta agrupar. |
| **5** | Relación · `fecha_vencimiento_contrato` | **Alerta de contratos por vencer** | 🟠 Mismo caso que los documentos: la fecha se guarda, nadie avisa. Un plazo fijo que vence sin aviso es un problema legal, no una molestia. |
| **6** | Novedad · `certificado_recibido_en` | **Licencias sin certificado / demora de presentación** | 🟠 El catálogo ya marca qué tipos exigen certificado, y la fecha de presentación se carga. La alerta "sin certificado tras X días" está descrita en la especificación y **no existe en el código**. |
| **7** | Empleado · `fecha_nacimiento` | **Cumpleaños del mes · pirámide etaria** | 🟠 Los cumpleaños figuran en el alcance acordado y no están implementados. Es el clásico "victoria fácil": alto valor percibido, esfuerzo mínimo. |
| **8** | Novedad · `cantidad_horas` | **Horas extra por mes / sector / empleado** | 🟠 El sistema **obliga** a cargar las horas y después no las suma nunca. Se está pidiendo un dato que no se mira: es el caso más flagrante del sistema. |
| **9** | Novedad · `fecha_aviso_empleado` | **Avisos tardíos** | 🟡 Comparar el aviso con el inicio de la ausencia mide cultura de trabajo. Dato cargado, cero uso. |
| **10** | Novedad · `fecha_hasta` (agregada) | **Días de ausentismo** (no solo eventos) | 🟡 El ranking de faltas ya calcula días — la misma lógica aplicada a licencias y accidentes convertiría el contador de eventos en una métrica de tiempo perdido real. |

### 8.2 Potencial medio — valen la pena cuando haya volumen

| Campo | Métrica potencial | Comentario |
|---|---|---|
| Novedad · `aprobada_por` / `aprobada_en` | **Tiempo de aprobación**; carga por aprobador | El dato se registra en cada aprobación. Con poco volumen dice poco; a escala revela cuellos de botella. |
| Relación · `antiguedad_en_dias` | **Antigüedad media**; rotación temprana (bajas < 90 días) | Ya se calcula por persona; falta agregarla. La rotación temprana es señal de problemas de selección o inducción. |
| Relación · `tipo_contrato` | **% de dotación por tipo de contrato** | Lista cerrada, agregable. Mide temporalidad/precarización de la dotación. |
| Relación · `jornada_legal` | **Dotación equivalente (FTE)** | Contar cabezas y contar jornadas no es lo mismo cuando hay medias jornadas. |
| Novedad · `fecha_fin_estimada` vs `fecha_hasta` | **Desvío de las licencias respecto de lo previsto** | Predictibilidad: cuánto se estiran en promedio las licencias médicas. |
| Novedad · `fecha_reintegro` | **Duración real vs. teórica** | Complementa la anterior. |
| Novedad · `novedad_origen` (agregado) | **% de licencias que se prorrogan**; largo de cadena | El dato ya se usa para no doble-contar; agregado mediría cuánto se subestiman las licencias al cargarlas. |
| Novedad · `estado` (agregado) | **Tasa de rechazo** | Un rechazo alto puede indicar criterios poco claros. |
| Empleado · `educacion` | **Perfil educativo por sector** | Lista cerrada, agregable. Valor real bajo hoy; se decide si se sigue pidiendo. |
| Empleado · `usuario` | **% de empleados con acceso** | Métrica de adopción, útil solo si se abre el sistema a los empleados. |

### 8.3 Candidatos a revisión — el dato existe pero no se puede analizar

Acá el problema **no es que falte la consulta**: es que **el campo, como está definido, no
se puede agregar**. Hay que decidir entre rediseñarlo o aceptar que es solo operativo.

| Campo | Problema | Opciones |
|---|---|---|
| Empleado · `art` | **Texto libre.** "La Segunda", "la segunda", "LA SEGUNDA ART" son tres aseguradoras distintas para el sistema. | Cruzado con las novedades de Accidente daría **siniestralidad por ART** — una métrica valiosa que hoy es imposible. **Convertirlo en catálogo** (como Sector o Puesto) es barato y lo desbloquea. |
| Empleado · `obra_social` | **Texto libre**, mismo problema. | Un padrón de obras sociales del grupo tiene valor para negociar. Si no se va a usar así, es solo dato de ficha — y está bien, pero conviene saberlo. |
| Empleado · `direccion` | Texto libre en un solo campo. | Sirve para ubicar a la persona, no para analizar. Con localidad separada se podría ver dispersión geográfica de la dotación (útil para transporte/logística). **Bajo prioridad.** |
| Empleado · `contacto_emergencia` | Nombre, vínculo y teléfono en un solo texto. | **No es un problema.** Nunca será métrica y no tiene que serlo: es información crítica en el peor momento. Se menciona para cerrar la lista, no para cambiarlo. |
| Empleado · `cuil` | Sin uso hoy. | **No tocar.** Es la llave natural para integrar con liquidación de sueldos. Su valor es futuro y es alto. |
| Novedad · `motivo` / `observaciones`, Empleado · `observaciones` | Texto libre. | **No son candidatos a eliminar.** El texto libre es donde va lo que no entra en ningún campo; su valor es cualitativo. Solo hay que no esperar métricas de ahí. |

### 8.4 Reservados — no tocar

| Campo | Estado |
|---|---|
| Empleado · `id_huella` | 🔒 Fase de asistencias. Se puebla desde ahora **a propósito**: el día que se conecte el reloj, el matching necesita el dato ya cargado. Vaciarlo ahora costaría recargarlo después. |
| Empleado · `exento_marcacion` | 🔒 Fase de asistencias. Ídem. |
| Novedad · `generada_automaticamente` | 🔒 Distinguirá la carga manual del cruce automático con el fichaje. |
| Novedad · `requiere_praxis` / `fecha_turno_praxis` | 🔒 Seguimiento de ART. Poco usado hoy; el valor aparece con volumen de accidentes. |
| Empleado/Relación · `creado_por`, `creado_en`, `actualizado_en` | Auditoría. No son métricas de negocio y no deben serlo. |

### 8.5 Veredicto en una tabla

| Veredicto | Campos | Acción sugerida |
|---|---|---|
| 🔴 **Métrica urgente, dato listo** | `fecha_vencimiento` (documentos), `clasificacion`, `motivo_egreso`, `sector`/`puesto` | Construir la consulta. El dato ya está. |
| 🟠 **Métrica de alto valor, dato listo** | `fecha_vencimiento_contrato`, `certificado_recibido_en`, `fecha_nacimiento`, `cantidad_horas` | Siguiente iteración. |
| 🟡 **Mejora incremental** | `fecha_aviso_empleado`, días de ausentismo, `aprobada_en`, antigüedad, `tipo_contrato`, `jornada_legal` | Cuando haya volumen. |
| 🔧 **Rediseñar para poder medir** | `art`, `obra_social` | Convertir a catálogo. Barato, desbloquea métricas. |
| ✅ **Correcto como está (operativo, no métrico)** | `contacto_emergencia`, `motivo`, `observaciones`, `direccion`, `telefono`, `email` | Ninguna. |
| 🔒 **Reservado a fase futura** | `id_huella`, `exento_marcacion`, `generada_automaticamente`, praxis, `cuil` | No tocar. |
| ❌ **Obsoleto / eliminar** | **Ninguno** | — |

> **La conclusión de fondo:** después de revisar los ~45 campos del sistema, **no hay un
> solo campo que convenga eliminar**. Los que no se usan se dividen en tres grupos, y
> ninguno es basura: los que esperan una consulta que nunca se escribió (la mayoría, y son
> los que más duelen), los que están reservados a propósito para fases futuras, y los que
> son operativos por naturaleza y nunca serán métrica.
>
> El problema del sistema **no es que se cargue de más: es que se lee de menos.** El dato
> está. Falta preguntarle.

---

## Anexo · Catálogos de referencia

**Educación:** Primario incompleto · Primario completo · Secundario incompleto ·
Secundario completo · Terciario · Universitario

**Jornada legal:** Completa (8h) · Reducida (6h) · Media (4h) · Rotativa

**Tipo de contrato:** Indeterminado · Plazo fijo · Eventual · Temporada · Pasantía

**Motivo de egreso:** Renuncia · Fin de contrato · Despido · Jubilación · Mudanza · Otro

**Estado de la relación laboral:** Activa · Finalizada

**Tipos de novedad:** Falta · Licencia médica · Accidente / ART · Vacaciones · Permiso ·
Horas extra

**Estados de novedad:** Registrada · En proceso · Aprobada · Rechazada · Cerrada · Anulada

**Clasificación de novedad:** Justificada · Injustificada

**Sectores, puestos y tipos de documento** son catálogos administrables: se agregan desde
el sistema sin tocar código.

---

*Documento generado a partir del código del repositorio (rama `fase-0-verificada`).*
*Ante cualquier diferencia entre este manual y el sistema, gana el sistema — y este
documento tiene un error que conviene reportar.*
