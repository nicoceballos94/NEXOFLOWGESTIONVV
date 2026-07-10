# Prompt para Claude Design — acciones en el detalle de novedad

> Copiar y pegar el bloque de abajo (entre los `---`) en el chat del proyecto de Claude Design.
> Origen: feedback de uso (2026-07-10). Falta poder **editar / aprobar / rechazar** una novedad
> desde su detalle: hoy una novedad recién cargada queda "Registrada" y no se puede hacer nada
> con ella (no se puede editar, ni aprobar para luego prorrogar). Los contratos de API reales
> están al final ("Contratos reales") como referencia para el cableado — no pegar en Claude Design.

---

En el modal de **detalle de una novedad** (el que se abre al hacer clic en una fila de la lista y muestra la cadena / línea de tiempo), hoy el pie solo tiene "Cerrar" y, cuando corresponde, "Prorrogar". Necesito agregar acciones **según el estado** de la novedad. No cambies el estilo visual general ni la estructura del modal, solo agregá estos botones con su lógica de visibilidad:

En el **pie del modal de detalle**, además de "Cerrar":

- **Editar** — visible **solo si la novedad está en estado "Registrada"**. Abre el formulario "Registrar novedad" ya existente, pero en **modo edición**: el título pasa a "Editar novedad" y los campos aparecen **precargados** con los datos de la novedad. (Igual que el botón "Editar" de la ficha de empleado reusa el formulario de alta.)
- **Aprobar** — botón primario (verde). Visible si el estado es **"Registrada" o "En proceso"**.
- **Rechazar** — visible si el estado es **"Registrada" o "En proceso"**.
- **Anular** — discreto, en rojo tenue. Visible si el estado **no es terminal** (o sea, ocultarlo cuando ya está "Anulada", "Rechazada" o "Cerrada").

La visibilidad de cada botón se decide por el **estado de la novedad que se está viendo**. Mantené el botón **"Prorrogar"** que ya existe (sigue apareciendo cuando la novedad es una Licencia/Accidente en estado "Aprobada").

Detalle de negocio para reflejar en la UI: una novedad **ya aprobada, rechazada, cerrada o anulada no se edita** (por eso "Editar" solo aparece en "Registrada"); para corregir una aprobada se anula y se recrea. Aprobar una Licencia/Accidente es lo que después habilita "Prorrogar".

---

## Contratos reales (referencia para el cableado — NO pegar en Claude Design)

Ya implementados en el backend. Base `/api/v1/`.

| Acción del botón | Llamada a la API | Condición |
|---|---|---|
| Editar (guardar) | `PATCH /novedades/{id}/` | Solo si estado = REGISTRADA |
| Aprobar | `POST /novedades/{id}/aprobar/` | Desde REGISTRADA o EN_PROCESO; exige rol RRHH/Admin |
| Rechazar | `POST /novedades/{id}/rechazar/` (body opc. `{motivo}`) | Desde REGISTRADA o EN_PROCESO; RRHH/Admin |
| Anular | `POST /novedades/{id}/anular/` (body opc. `{motivo}`) | Bloqueado si es la madre con prórrogas activas; RRHH/Admin |
| Prorrogar | `POST /novedades/{id}/prorrogar/` | Solo Licencia/Accidente APROBADA (ya cableado) |

Notas:
- Los estados **EN_PROCESO** y **CERRADA** existen en el enum pero todavía **no tienen endpoint** de
  transición (no hay botón que lleve a ellos por ahora; se agregan si el workflow lo pide).
- La visibilidad por estado la maneja el view-model del detalle (como ya hace `puedeProrrogar`),
  así funciona igual con los datos reales del backend.
