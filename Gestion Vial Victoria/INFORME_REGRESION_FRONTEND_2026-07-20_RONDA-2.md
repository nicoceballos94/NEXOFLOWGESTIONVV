# Segunda regresión del frontend — Ceibo RRHH

**Fecha:** 20/07/2026  
**Base:** `INFORME_REGRESION_FRONTEND_2026-07-20.md`  
**Build:** `frontend/dist/index.html` del 20/07/2026 16:08  
**Entorno:** navegador real, Django/PostgreSQL local, origen limpio y origen con caché previa, escritorio 1280×720 y móvil 390×844.

## Resultado ejecutivo

Los **cinco problemas pendientes de la regresión anterior están corregidos**. El smoke test funcional y visual de los módulos principales también fue satisfactorio.

- **0 errores de consola.**
- **0 advertencias de consola.**
- **0 fallas críticas o altas nuevas** dentro del alcance ejecutado.
- **1 inconsistencia menor transitoria:** el badge de Novedades muestra el número mock `7` durante la carga y cambia a `12` cuando responde la API.

## Revalidación de pendientes anteriores

| Pendiente anterior | Estado | Evidencia |
|---|---|---|
| REG-01 · Mezcla incompatible de assets desde caché | **Corregido** | El build publica `support.c2dad9138a.js` y `ceibo-api.7c42765358.js`. El origen usado en pruebas anteriores cargó la nueva versión sin reutilizar el JS viejo y sin `notifVals is not a function`. |
| REG-02 · Datos mock antes de cargar la API | **Corregido en el contenido principal** | El `<main>` muestra `Cargando datos…` con `role="status"`; no aparecen KPIs, alertas ni rankings falsos. Al finalizar, aparecen los 12 empleados y 12 novedades reales. Queda el detalle menor del badge lateral, documentado abajo. |
| REG-03 · Menú móvil sin nombres accesibles | **Corregido** | A 390×844 los seis botones conservan nombres: Dashboard, Empleados, Novedades, Alertas y vencimientos, Reportes y métricas y Configuración. |
| REG-04 · Novedades ilegible en móvil | **Corregido** | Las filas se transforman en tarjetas verticales. Tipo y estado ocupan la cabecera; empleado, fecha y clasificación aparecen en filas rotuladas, sin solapamientos ni scroll horizontal. |
| REG-05 · Scroll conservado entre módulos | **Corregido** | Se desplazó Dashboard a `scrollTop = 600`; al navegar a Novedades el nuevo módulo abrió en `scrollTop = 0`. |

## Hallazgo menor pendiente

### REG2-01 — Badge mock de Novedades durante la carga

- **Severidad:** Baja / P3
- **Resultado observado:** mientras el contenido principal muestra correctamente `Cargando datos…`, el botón lateral anuncia temporalmente `Novedades 7`. Después de cargar la API cambia a `Novedades 12`.
- **Impacto:** es breve y no bloquea el uso, pero sigue exponiendo un dato de ejemplo como si fuera real.
- **Recomendación:** mientras `state.novedades === null`, ocultar el badge, mostrar `…` o anunciar “Novedades cargando”. Renderizar el número únicamente después de recibir la API.

## Smoke test funcional

| Caso | Resultado |
|---|---|
| Pantalla inicial de carga | **Correcto** — solo muestra estado de carga, sin KPIs mock. |
| Carga de catálogos | **Correcto** — 2 empresas, 4 sectores, 11 puestos y 6 tipos de novedad. |
| Carga de empleados | **Correcto** — 12 empleados desde backend. |
| Carga de novedades | **Correcto** — 12 cadenas desde backend. |
| Dashboard Mensual/Anual | **Correcto** — Anual muestra “últimos 12 meses” y delta de 36,9 puntos. |
| Búsqueda `maria` | **Correcto** — encuentra las tres variantes con y sin tilde. |
| Apertura de ficha | **Correcto** — se abrió Diego Fernández. |
| Edición segura | **Correcto** — DNI, empresa, sector, puesto, ingreso, jornada y estado están bloqueados. |
| Modal y foco | **Correcto** — `role="dialog"`, `aria-modal="true"` y foco en Nombre y apellido. |
| Alta de novedad | **Correcto hasta guardar** — solo ofrece Registrada, Aprobada, Rechazada y Anulada. |
| Reportes demo | **Correcto** — banner visible y sin el total falso 134. |
| Configuración | **Correcto** — explica qué no persiste y los botones +/− tienen nombre contextual. |
| Novedades móvil | **Correcto** — tarjetas legibles sin superposición. |
| Navegación móvil accesible | **Correcto** — botones con nombres accesibles. |
| Reinicio de scroll | **Correcto** — cada módulo abre arriba. |
| Actualización con caché previa | **Correcto** — carga los assets hasheados correspondientes. |
| Consola del navegador | **Correcto** — sin errores ni warnings. |

## Alcance y preservación de datos

No se confirmaron altas, ediciones, bajas, reingresos, transiciones de novedades, cargas de archivos ni cambios de configuración. Los formularios se probaron hasta el paso anterior a guardar. No se modificaron datos reales.

## Conclusión

El frontend queda en un estado considerablemente más sólido para continuar con QA funcional de escritura. El siguiente paso recomendado es ejecutar los flujos persistentes sobre una base descartable de QA y agregar pruebas E2E automatizadas para impedir regresiones en carga inicial, actualización de assets, navegación responsive y formularios.

