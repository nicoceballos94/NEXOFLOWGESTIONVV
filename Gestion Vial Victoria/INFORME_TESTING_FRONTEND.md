# Informe de testing profesional del frontend — Ceibo RRHH

**Fecha:** 20/07/2026  
**Aplicación probada:** `frontend/dist` contra Django/PostgreSQL local  
**Resoluciones:** escritorio (1280×720 aprox.) y móvil (390×844)  
**Tipo de revisión:** funcional exploratoria, integración frontend/API, responsive, consistencia visual, UX y accesibilidad básica.

## Resumen ejecutivo

El frontend permite consultar correctamente empleados, fichas, novedades, alertas y datos operativos del dashboard. La conexión con la API funcionó durante toda la prueba y no se registraron errores ni advertencias en la consola del navegador.

Sin embargo, el producto todavía no debería considerarse confiable para uso operativo sin corregir los hallazgos críticos. Los problemas más importantes son:

1. **Reportes muestra métricas de ejemplo que contradicen los datos reales.** Por ejemplo, Dashboard informa 12 empleados activos y Reportes muestra 134.
2. **El formulario de edición ofrece campos que luego no guarda.** DNI, sector, puesto, fecha de ingreso, jornada y estado parecen editables, pero el `PATCH` solo envía datos personales.
3. **El alta de novedades permite seleccionar “En proceso” y “Cerrada”, pero esos estados no se aplican.** La novedad queda registrada en otro estado sin advertencia.
4. **La experiencia móvil de listados y configuración es deficiente:** datos superpuestos, columnas comprimidas y textos de una palabra por línea.
5. **Hay barreras importantes de accesibilidad:** navegación y filas clicables implementadas como `<div>`, modales sin semántica de diálogo y formularios sin `<label>` asociados.

## Hallazgos priorizados

### BUG-01 — Reportes muestra datos simulados como si fueran reales

- **Severidad:** Crítica / P1
- **Módulo:** Reportes y métricas
- **Resultado observado:** Dashboard mostró **12 empleados activos**, mientras Reportes mostró **134 empleados activos, ▲ 13,6%**. Los porcentajes de ausentismo y egresos también están definidos de forma fija.
- **Riesgo:** una persona de RRHH puede tomar decisiones basadas en cifras falsas sin ninguna indicación de que son datos de demostración.
- **Evidencia técnica:** los porcentajes están hardcodeados en `frontend/dist/index.html` líneas 1561–1566; el README reconoce que Reportes usa datos de ejemplo.
- **Recomendación:** conectar Reportes a endpoints reales o bloquear el módulo con una etiqueta visible “Próximamente / Datos de demostración”. Nunca mezclar mock y producción sin señalización.

### BUG-02 — La edición de empleado descarta cambios silenciosamente

- **Severidad:** Crítica / P1
- **Módulo:** Empleados → Ficha → Editar
- **Campos afectados:** DNI, sector, puesto, fecha de ingreso, jornada legal, estado y posiblemente otros datos de la relación laboral.
- **Resultado observado:** todos esos controles están habilitados y parecen guardables. Sin embargo, en modo edición `submitAlta()` ejecuta un `PATCH /empleados/{id}/` con datos personales y retorna; no envía los campos de relación laboral. Solo la empresa está correctamente bloqueada y explicada.
- **Riesgo:** el usuario recibe una falsa sensación de éxito y puede creer que modificó información laboral sensible cuando el sistema la conserva sin cambios.
- **Recomendación:** deshabilitar y explicar todos los campos que no se editan desde esa operación, o implementar endpoints/acciones específicas para modificar la relación laboral. Después de guardar, volver a leer el registro y mostrar confirmación de los campos realmente persistidos.

### BUG-03 — Estados “En proceso” y “Cerrada” no se aplican al crear una novedad

- **Severidad:** Crítica / P1
- **Módulo:** Novedades → Nueva novedad
- **Pasos:** abrir “Nueva novedad” y revisar el selector Estado.
- **Resultado observado:** el selector ofrece Registrada, En proceso, Aprobada, Rechazada, Cerrada y Anulada. La integración solo mapea acciones para Aprobada, Rechazada y Anulada. “En proceso” y “Cerrada” no generan transición, por lo que la novedad queda en su estado inicial sin advertencia.
- **Riesgo:** inconsistencia operativa y seguimiento incorrecto de ausencias/accidentes.
- **Recomendación:** retirar temporalmente las opciones sin soporte o crear las transiciones de backend correspondientes. Si una transición falla o no existe, no cerrar el modal y mostrar un error explícito.

### BUG-04 — El selector Mensual/Anual no actualiza la métrica de rotación

- **Severidad:** Alta / P2
- **Módulo:** Dashboard
- **Pasos:** abrir Dashboard y pulsar “Anual”.
- **Resultado observado:** “Anual” queda visualmente activo, pero permanecen **59,1%**, **▲ 59,1 pts**, el texto **“vs. mes anterior”** y la misma serie mensual.
- **Riesgo:** el control afirma cambiar el período, pero los datos visibles no cambian.
- **Recomendación:** corregir la derivación/renderizado de `dashboardVals()` al cambiar `state.rot` y agregar una prueba que verifique valor, etiqueta de período y serie.

### BUG-05 — Listado de empleados ilegible en móvil

- **Severidad:** Alta / P2
- **Módulo:** Empleados
- **Resolución:** 390×844
- **Resultado observado:** la grilla de seis columnas se comprime dentro de unos 264 px útiles. Avatar, nombre, DNI, empresa y sector se superponen; parte de la información queda fuera o resulta imposible de asociar.
- **Evidencia técnica:** la grilla conserva `grid-template-columns: 2.2fr 1.3fr 1fr 1.1fr 0.9fr 42px` también bajo 900 px. El único breakpoint reduce la barra lateral, pero no adapta el contenido.
- **Recomendación:** en móvil transformar cada fila en tarjeta vertical (nombre/DNI arriba; empresa, sector, puesto y estado debajo) o habilitar un patrón de tabla responsive claramente desplazable.

### BUG-06 — Configuración se comprime excesivamente en móvil

- **Severidad:** Alta / P2
- **Módulo:** Configuración
- **Resolución:** 390×844
- **Resultado observado:** las descripciones quedan con una palabra por línea y los botones ocupan el ancho restante. La lectura es muy lenta y aumenta mucho la altura de cada fila.
- **Recomendación:** apilar descripción y control numérico en dos filas bajo 600 px; reducir/eliminar el texto secundario o mostrarlo en ayuda contextual.

### BUG-07 — Destinatarios y canales aparentan guardarse, pero solo cambian en memoria

- **Severidad:** Alta / P2
- **Módulo:** Configuración → Destinatarios y canales
- **Resultado observado:** los chips y switches cambian visualmente, pero `toggleRole()` y `toggleCanal()` solo actualizan estado local. No existe guardado, confirmación ni llamada a API; al recargar se pierden.
- **Riesgo:** el usuario cree que configuró notificaciones que nunca serán enviadas.
- **Recomendación:** persistir la configuración en backend y mostrar estado de guardado. Hasta entonces, deshabilitar el bloque o marcarlo claramente como no disponible.

### BUG-08 — Búsqueda de empleados no ignora tildes

- **Severidad:** Media / P2
- **Módulo:** Empleados
- **Pasos:** buscar `maria`.
- **Resultado observado:** aparece “Maria Agust Cardoso”, pero no “María Godoy” ni “María López”.
- **Causa:** el filtro del componente usa `toLowerCase().indexOf()` sin normalización de acentos.
- **Recomendación:** normalizar consulta y campos con Unicode NFD y quitar marcas diacríticas antes de comparar.

### BUG-09 — El contador usa una etiqueta incorrecta con filtros de estado

- **Severidad:** Media / P2
- **Módulo:** Empleados
- **Resultado observado:** al seleccionar Inactivos aparece, por ejemplo, “Mostrando 0 de 12 activos”. La palabra y el denominador siguen referidos a activos aunque el filtro sea Todos o Inactivos.
- **Evidencia técnica:** `empCountLbl` siempre usa `totalActivos` y el literal “activos”.
- **Recomendación:** calcular denominador y etiqueta según el filtro actual: “0 inactivos”, “12 activos” o “12 empleados”.

### BUG-10 — El buscador global conserva un término fuera de contexto

- **Severidad:** Media / P3
- **Módulos:** todos
- **Resultado observado:** después de buscar “Diego” y navegar a Novedades, Alertas, Reportes o Configuración, el encabezado continúa mostrando “Diego”, aunque esos módulos no están filtrados por ese valor. Escribir en el campo cambia automáticamente a Empleados.
- **Riesgo:** el usuario puede creer que los datos del módulo actual están filtrados.
- **Recomendación:** aclarar el propósito (“Buscar y abrir empleado”), limpiar el valor al abandonar Empleados o convertirlo en una búsqueda global real con resultados desplegables.

### BUG-11 — Navegación, filas y switches no son accesibles por teclado

- **Severidad:** Alta / P2
- **Módulos:** transversal
- **Resultado observado:** elementos interactivos clave están implementados como `<div onClick>` sin `role`, `tabindex` ni evento de teclado: navegación lateral, filas de empleados/novedades y switches de canales.
- **Impacto:** usuarios de teclado o tecnología asistiva no pueden operar funciones principales de forma confiable.
- **Recomendación:** usar `<a>`/`<button>` reales; para switches usar `<button role="switch" aria-checked="…">`; añadir nombres accesibles visibles.

### BUG-12 — Modales y formularios carecen de semántica accesible

- **Severidad:** Alta / P2
- **Módulos:** altas, edición, baja, documentos y novedades
- **Resultado observado:** el modal de empleado no tiene `role="dialog"`, `aria-modal="true"` ni título asociado. En la inspección DOM había **0 elementos `<label>`**; los textos visuales son `<div>` separados. Los controles dependen principalmente del placeholder.
- **Impacto:** lectores de pantalla no relacionan correctamente cada campo con su nombre; tampoco se anuncia la apertura del diálogo ni se garantiza el foco.
- **Recomendación:** asociar cada control con `<label for>`, implementar semántica de diálogo, mover el foco al abrir, contenerlo dentro del modal y devolverlo al botón originador al cerrar.

### UX-01 — Formato de nombres inconsistente

- **Severidad:** Baja / P3
- **Resultado observado:** una misma interfaz mezcla “Carla Benítez” con “Benítez, Carla”, “Maria Agust Cardoso” con “Agust Cardoso, Maria” y “TESTE 13” con “13, TESTE”.
- **Recomendación:** adoptar un único formato visible (`Nombre Apellido`) y conservar el orden alternativo solo para exportes o vistas administrativas específicas.

### UX-02 — Botones +/− sin nombre contextual

- **Severidad:** Baja / P3
- **Módulo:** Configuración
- **Resultado observado:** todos los controles repiten los nombres accesibles “+” y “−”. Una tecnología asistiva no puede saber cuál modifica Apto médico, CNRT, Carnet, etc.
- **Recomendación:** usar `aria-label="Aumentar días de aviso para Apto médico"` y equivalente para cada fila.

## Casos de uso que funcionan correctamente

| Caso de uso | Resultado | Observación |
|---|---|---|
| Inicio automático y conexión con API | Correcto | Cargó catálogos, empleados y novedades contra Django/PostgreSQL. |
| Dashboard: KPIs principales | Correcto | Mostró 12 activos, ingresos, egresos y ausentismo con datos del backend. |
| Dashboard: alertas del día | Correcto | Certificados y documentos vencidos/próximos se renderizaron correctamente. |
| Alternar tema claro/oscuro | Correcto | `data-th` cambió a `light` y se aplicó la paleta clara. |
| Lista de empleados | Correcto en escritorio | Renderizó 12 activos con empresa, sector, puesto y estado. |
| Filtros por estado/empresa/sector | Correcto funcionalmente | El resultado se filtra, aunque el contador textual es incorrecto. |
| Búsqueda exacta sin tildes | Correcto | Buscar “Diego” devolvió y abrió a Diego Fernández. |
| Ficha de empleado | Correcto | Datos personales, relación laboral, novedades y documentación cargaron. |
| Lista de novedades | Correcto | Mostró 11 cadenas con tipo, empleado, fechas, clasificación y estado. |
| Detalle de novedad | Correcto | Se abrió la cadena, vigencia y sección de respaldos. |
| Alertas y vencimientos | Correcto | Resumen y agrupación por tipo de documento provinieron del backend. |
| Configuración de días de aviso | Correcto en lectura | Los umbrales se cargaron desde backend; no se alteraron durante esta auditoría. |
| Formulario de alta en móvil | Aceptable | El modal entra en pantalla y tiene desplazamiento interno; la grilla de dos columnas queda algo estrecha. |
| Estabilidad técnica durante navegación | Correcto | Sin errores ni advertencias de consola en los recorridos realizados. |

## Casos no ejecutados de forma destructiva

Para preservar los datos existentes no confirmé acciones que modifican el sistema: alta/edición/baja/reingreso de empleados, creación/transición de novedades, carga/eliminación de documentos o respaldos y cambio de umbrales. Estos flujos fueron inspeccionados hasta el paso previo a guardar y se revisó su cableado en código. Para certificar escritura y rollback conviene ejecutarlos en una base de QA descartable con datos semilla conocidos.

## Recomendación de orden de corrección

1. **Evitar información falsa:** ocultar Reportes mock y opciones de estado no soportadas.
2. **Evitar pérdida silenciosa:** corregir el formulario Editar empleado y confirmar persistencia real.
3. **Corregir Dashboard Anual y persistencia de configuración.**
4. **Hacer responsive Empleados, Novedades, Reportes y Configuración.**
5. **Aplicar una base de accesibilidad:** elementos semánticos, labels, diálogos, foco y teclado.
6. **Pulir búsqueda, contadores, nombres y textos contextuales.**

## Criterio de salida sugerido para la próxima versión

- Cero datos mock presentados como reales.
- Cero campos editables que no persistan.
- Pruebas E2E de alta, edición, baja, reingreso y estados de novedades sobre una base QA.
- Sin superposición de contenido a 390, 768, 1024 y 1440 px.
- Navegación completa solo con teclado.
- Todos los campos con nombre accesible y todos los modales con manejo de foco.
- Prueba automatizada que compare los KPIs de Dashboard y Reportes para el mismo período.
