"""Bitácora del sistema: quién hizo qué, sobre qué y cuándo (§14 del diseño, RP8).

Una sola tabla para todo el dominio, en vez de una tabla-espejo por modelo
(`django-simple-history` y compañía). El motivo es la pregunta que se le hace de verdad
a una auditoría de RRHH —"¿quién tocó esta ficha?"—, que acá es un solo
`WHERE entidad=… AND objeto_id=…` y no un UNION de seis tablas.

Dos tipos de evento conviven en la misma tabla, a propósito:
- **Cambios de datos** (`EMPLEADO_ACTUALIZADO`): el interés está en el diff.
- **Hechos del negocio** (`NOVEDAD_RECHAZADA`): el interés está en la acción misma; el
  diff es anecdótico. Separarlos en dos tablas obligaría a intercalarlas a mano para
  mostrar la historia de un objeto, que es justo lo que se quiere leer.

⚠️ **PII.** Los diffs de `Empleado` llevan DNI y CUIL, y los de `Novedad` pueden llevar
motivos médicos: esta tabla concentra lo más sensible del sistema en un solo lugar. La
lectura es **solo Admin** y no se expone sin filtro. Nunca se guarda el contenido de un
archivo, solo su nombre (ver `services._valor_json`).

No hereda de `ModeloBase`: un registro de auditoría no se crea, se *asienta*. No tiene
`actualizado_en` porque es inmutable, y su `creado_por` es `usuario`, que es el dato.
"""
from django.conf import settings
from django.db import models


class Accion(models.TextChoices):
    """Vocabulario cerrado de eventos. Semántico, no CRUD.

    "Relación finalizada" es un hecho del negocio que se entiende leyéndolo; el
    `UPDATE relacion_laboral SET estado='FINALIZADA'` equivalente no le dice nada a nadie.
    Agregar una acción es agregar un renglón acá y llamarla desde el service que la produce.
    """

    # Empleados
    EMPLEADO_CREADO = "EMPLEADO_CREADO", "Empleado creado"
    EMPLEADO_ACTUALIZADO = "EMPLEADO_ACTUALIZADO", "Empleado actualizado"
    EMPLEADO_FOTO_CAMBIADA = "EMPLEADO_FOTO_CAMBIADA", "Foto de empleado cambiada"
    EMPLEADO_FOTO_ELIMINADA = "EMPLEADO_FOTO_ELIMINADA", "Foto de empleado eliminada"
    # Relación laboral
    RELACION_CREADA = "RELACION_CREADA", "Relación laboral creada"
    RELACION_FINALIZADA = "RELACION_FINALIZADA", "Relación laboral finalizada (baja)"
    # Documentos del legajo
    DOCUMENTO_CREADO = "DOCUMENTO_CREADO", "Documento cargado"
    DOCUMENTO_ACTUALIZADO = "DOCUMENTO_ACTUALIZADO", "Documento actualizado"
    DOCUMENTO_ELIMINADO = "DOCUMENTO_ELIMINADO", "Documento eliminado"
    # Novedades
    NOVEDAD_CREADA = "NOVEDAD_CREADA", "Novedad creada"
    NOVEDAD_ACTUALIZADA = "NOVEDAD_ACTUALIZADA", "Novedad actualizada"
    NOVEDAD_APROBADA = "NOVEDAD_APROBADA", "Novedad aprobada"
    NOVEDAD_RECHAZADA = "NOVEDAD_RECHAZADA", "Novedad rechazada"
    NOVEDAD_ANULADA = "NOVEDAD_ANULADA", "Novedad anulada"
    NOVEDAD_PRORROGADA = "NOVEDAD_PRORROGADA", "Novedad prorrogada"
    CADENA_ANULADA = "CADENA_ANULADA", "Cadena de prórrogas anulada"
    ADJUNTO_AGREGADO = "ADJUNTO_AGREGADO", "Adjunto agregado a novedad"
    ADJUNTO_ELIMINADO = "ADJUNTO_ELIMINADO", "Adjunto eliminado de novedad"
    # Checklists de ingreso/egreso
    CHECKLIST_ITEM_COMPLETADO = "CHECKLIST_ITEM_COMPLETADO", "Ítem de checklist completado"
    CHECKLIST_ITEM_REVERTIDO = "CHECKLIST_ITEM_REVERTIDO", "Ítem de checklist destildado"
    # Usuarios
    USUARIO_CREADO = "USUARIO_CREADO", "Usuario creado"
    USUARIO_ACTUALIZADO = "USUARIO_ACTUALIZADO", "Usuario actualizado"
    USUARIO_DESACTIVADO = "USUARIO_DESACTIVADO", "Usuario desactivado"


class RegistroAuditoria(models.Model):
    """Un hecho asentado. Inmutable: se inserta y no se toca nunca más."""

    momento = models.DateTimeField(auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Null si lo hizo un proceso automático, o si el usuario se borró después.",
    )
    usuario_nombre = models.CharField(
        max_length=150,
        blank=True,
        help_text="Copia congelada del username. La FK es SET_NULL: sin esto, borrar un "
        "usuario dejaría media bitácora sin autor, que es lo único que no puede pasar.",
    )
    accion = models.CharField(max_length=40, choices=Accion.choices, db_index=True)
    entidad = models.CharField(
        max_length=50, help_text='Nombre del modelo afectado ("Empleado", "Novedad"…).'
    )
    objeto_id = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="PK del objeto. Queda null si el objeto se borró."
    )
    empleado = models.ForeignKey(
        "empleados.Empleado",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="De qué PERSONA habla el evento, aunque `entidad` sea otra cosa. "
        "Denormalizado a propósito: sin esto, 'el historial de la ficha de Juan' obliga a "
        "juntar eventos de Empleado, RelacionLaboral, DocumentoEmpleado, Novedad e "
        "ItemProceso averiguando antes cuáles son de Juan. Null en eventos que no son de "
        "nadie en particular (un usuario del sistema sin empleado asociado).",
    )
    objeto_repr = models.CharField(
        max_length=200,
        blank=True,
        help_text='Texto legible del objeto al momento del hecho ("Pérez, Juan (leg. 0042)"). '
        "Congelado: si el objeto se borra o se renombra, la bitácora sigue diciendo de "
        "quién hablaba.",
    )
    valores_antes = models.JSONField(
        default=dict, blank=True, help_text="Solo los campos que cambiaron. {} en un alta."
    )
    valores_despues = models.JSONField(
        default=dict, blank=True, help_text="Solo los campos que cambiaron. {} en una baja."
    )
    ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Origen de la request. Sin llenar en MVP1: los services reciben el actor, "
        "no la request. Se completa con un middleware cuando haga falta, sin migración.",
    )

    class Meta:
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"
        ordering = ["-momento", "-id"]
        indexes = [
            # La consulta central: la historia de un objeto ("¿quién tocó esta ficha?").
            models.Index(fields=["entidad", "objeto_id", "-momento"], name="idx_audit_objeto"),
            # La consulta transversal: "¿qué hizo Juan el martes?".
            models.Index(fields=["usuario", "-momento"], name="idx_audit_usuario"),
            # La pestaña "Historial" de la ficha: todo lo que le pasó a una persona.
            models.Index(fields=["empleado", "-momento"], name="idx_audit_empleado"),
        ]

    def __str__(self):
        return f"{self.momento:%d/%m/%Y %H:%M} · {self.get_accion_display()} · {self.objeto_repr}"
