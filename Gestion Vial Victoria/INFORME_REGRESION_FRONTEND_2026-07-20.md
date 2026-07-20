# Informe de regresión del frontend — Ceibo RRHH

**Fecha:** 20/07/2026  
**Base:** hallazgos de `INFORME_TESTING_FRONTEND.md`  
**Build verificado:** `frontend/dist/index.html` generado el 20/07/2026 13:49  
**Entorno:** navegador real, Django/PostgreSQL local, escritorio 1280×720 y móvil 390×844.

## Resultado ejecutivo

La regresión confirma una mejora importante. De los 14 hallazgos originales:

- **11 están corregidos.**
- **2 están mitigados de forma transparente** mientras falta funcionalidad de backend.
- **1 está corregido en gran parte, pero conserva una falla móvil de accesibilidad.**

La aplicación funciona correctamente cuando todos los archivos estáticos se cargan desde cero. No hubo errores ni advertencias de consola durante el recorrido sobre un origen limpio.

No obstante, se detectaron **cinco problemas pendientes o nuevos**. El más serio es una incompatibilidad de caché capaz de dejar la aplicación sin contenido después de actualizarla. También continúa rota la tabla de Novedades en móvil.

## Estado de los hallazgos anteriores

| Hallazgo anterior | Estado | Evidencia de regresión |
|---|---|---|
| BUG-01 · Reportes simulados como reales | **Mitigado** | Ahora aparece un banner visible “Datos de demostración”, se explica que el módulo no está conectado y se eliminó el total falso de 134. |
| BUG-02 · Edición descarta campos silenciosamente | **Corregido** | DNI, empresa, sector, puesto, fecha de ingreso, jornada y estado están deshabilitados en edición. Los datos personales editables conservan nombres accesibles. |
| BUG-03 · Estados no soportados al crear novedades | **Corregido** | En el alta solo quedan Registrada, Aprobada, Rechazada y Anulada. “En proceso” y “Cerrada” ya no se ofrecen. |
| BUG-04 · Mensual/Anual no actualiza rotación | **Corregido** | “Anual” cambia el período a “últimos 12 meses” y recalcula el delta de 59,1 a 36,9 puntos. |
| BUG-05 · Empleados ilegible en móvil | **Corregido** | Cada fila se transforma en tarjeta vertical, sin solapamientos ni scroll horizontal. |
| BUG-06 · Configuración comprimida en móvil | **Corregido** | Descripción y controles se apilan; cada fila conserva ancho legible. |
| BUG-07 · Destinatarios/canales aparentan guardarse | **Mitigado** | La interfaz explica que no se guardan y cualquier clic muestra un aviso de que falta el módulo de notificaciones. |
| BUG-08 · Búsqueda sin normalización de tildes | **Corregido** | Buscar `maria` devuelve Maria Agust Cardoso, María Godoy y María López. |
| BUG-09 · Contador siempre decía “activos” | **Corregido** | “Todos” informa empleados y “Inactivos” muestra correctamente “0 de 0 inactivos”. |
| BUG-10 · Buscador conserva términos fuera de contexto | **Corregido** | El término se limpia al navegar a otros módulos. |
| BUG-11 · Elementos no operables por teclado | **Parcial** | Navegación, filas y switches ahora usan botones/roles y las filas tienen `tabindex`. En móvil, los botones del menú vuelven a quedar sin nombre accesible; ver REG-03. |
| BUG-12 · Modales y formularios sin semántica | **Corregido** | Los modales tienen `role="dialog"`, `aria-modal="true"`, nombre y foco inicial. Los controles reciben `aria-label` desde su etiqueta visible. |
| UX-01 · Formato inconsistente de nombres | **Corregido** | Alertas y listados usan “Nombre Apellido” de forma consistente en los datos revisados. |
| UX-02 · Botones +/− sin contexto | **Corregido** | Se anuncian, por ejemplo, como “Aumentar días de aviso para Apto médico”. |

## Problemas pendientes o nuevos

### REG-01 — Una actualización puede combinar archivos incompatibles desde caché

- **Severidad:** Crítica / P1
- **Resultado observado:** al abrir la versión actual en el origen ya utilizado (`127.0.0.1:8080`), `index.html` nuevo llamó a `window.CeiboAPI.notifVals`, pero el navegador reutilizó un `ceibo-api.js` anterior. La aplicación mostró solo la barra lateral y un `<main>` vacío.
- **Error de consola:** `TypeError: window.CeiboAPI.notifVals is not a function`.
- **Confirmación:** al servir exactamente el mismo `dist` desde un origen limpio (`127.0.0.1:8081`), la función estuvo disponible y toda la aplicación cargó correctamente.
- **Causa probable:** `index.html` referencia `./ceibo-api.js` y `./support.js` con nombres estables, sin hash ni versión. Una actualización parcial de caché puede mezclar contratos incompatibles.
- **Riesgo:** después de desplegar, usuarios con una sesión previa pueden encontrar la aplicación en blanco aunque el código publicado sea correcto.
- **Recomendación:** generar nombres con hash de contenido (`ceibo-api.<hash>.js`) o agregar versión al URL; servir `index.html` con `Cache-Control: no-cache` y assets hasheados con caché inmutable. Añadir una prueba de actualización desde la versión anterior.

### REG-02 — Se muestran datos mock antes de completar la carga de la API

- **Severidad:** Alta / P2
- **Módulo:** Dashboard e inicio
- **Resultado observado:** inmediatamente después de abrir el build limpio, el Dashboard mostró temporalmente 134 activos, 6 ingresos, 2 egresos, alertas y rankings simulados. Aproximadamente un segundo después fueron reemplazados por los datos reales: 12 activos, 8 ingresos, 5 egresos y 12 novedades.
- **Riesgo:** en redes lentas el usuario ve información falsa durante varios segundos y puede comenzar a interpretarla antes de que cambie.
- **Recomendación:** iniciar los estados de datos en `null` y mostrar skeletons o “Cargando…”. Los mocks deben vivir únicamente en entornos de demostración explícitos.

### REG-03 — El menú lateral pierde sus nombres accesibles en móvil

- **Severidad:** Alta / P2
- **Resolución:** 390×844
- **Resultado observado:** el snapshot accesible muestra seis `button` sin nombre en la navegación lateral.
- **Causa:** el nombre depende de `<span class="ceibo-navlbl">`; el breakpoint lo oculta con `display:none`, retirándolo también del árbol de accesibilidad. Los botones no tienen `aria-label` propio.
- **Impacto:** un lector de pantalla anuncia “botón” sin indicar Dashboard, Empleados, Novedades, etc.
- **Recomendación:** agregar `aria-label` permanente a cada botón o esconder el texto solo visualmente con una clase `sr-only` que conserve el nombre accesible.

### REG-04 — Novedades continúa ilegible en móvil

- **Severidad:** Alta / P2
- **Resolución:** 390×844
- **Resultado observado:** la grilla de cinco columnas conserva el layout de escritorio. Las dos primeras columnas llegan a ancho 0; tipo, empleado, fecha y badges se superponen. El encabezado queda cortado.
- **Evidencia geométrica:** primera fila de 252 px de ancho; columnas Tipo y Empleado midieron 0 px, mientras Fecha, Clasificación y Estado ocuparon el resto.
- **Recomendación:** aplicar a `.ceibo-nov-row` el mismo patrón de tarjeta móvil usado correctamente en Empleados, con etiquetas Tipo, Empleado, Fecha, Clasificación y Estado. Ocultar el encabezado de tabla bajo 700 px.

### REG-05 — La posición de scroll se conserva al cambiar de módulo

- **Severidad:** Media / P2
- **Resultado observado:** al navegar desde Configuración hacia Empleados, el nuevo módulo abrió con `main.scrollTop = 137`; al ir luego a Novedades conservó 42,5 px. El título y los primeros filtros quedaron parcialmente ocultos y superpuestos con el encabezado.
- **Riesgo:** el usuario cree que faltan filtros o aterriza en mitad de una lista diferente.
- **Recomendación:** en `setView()` llevar el contenedor principal a `scrollTop = 0`, o usar un contenedor independiente por ruta/vista con restauración de scroll controlada.

## Casos revalidados correctamente

- Carga de catálogos, 12 empleados y 12 cadenas de novedades desde Django/PostgreSQL.
- Dashboard con KPIs, alertas y ranking reales después de finalizar la carga.
- Cambio Mensual/Anual.
- Búsqueda de empleados con y sin tildes.
- Contadores de Todos, Activos e Inactivos.
- Apertura de ficha y modal de edición.
- Bloqueo de campos laborales que no se guardan desde la edición personal.
- Alta de novedad hasta el paso previo a guardar y catálogo de estados permitido.
- Reportes claramente identificados como demostración.
- Umbrales reales de vencimientos y nombres accesibles de controles +/−.
- Aviso explícito para destinatarios/canales todavía no implementados.
- Tarjetas móviles de empleados.
- Layout móvil de configuración.
- Semántica de filas, switches y modales.
- Foco inicial en el primer campo del diálogo.
- Ausencia de errores de consola sobre un origen sin caché previa.

## Alcance y datos

No se confirmaron operaciones destructivas o persistentes: alta, edición, baja o reingreso de empleados; creación o transición de novedades; documentos/adjuntos; ni modificación de umbrales. La regresión inspeccionó esos flujos hasta el paso previo al guardado y verificó su cableado visible. El único clic en Configuración disparó el nuevo aviso informativo y no llamó a una operación de escritura.

## Prioridad recomendada

1. Resolver versionado/caché de assets antes del próximo despliegue.
2. Reemplazar los mocks iniciales por estados de carga.
3. Adaptar Novedades a tarjeta móvil.
4. Agregar nombres accesibles permanentes al menú móvil.
5. Reiniciar/restaurar correctamente el scroll al navegar.

