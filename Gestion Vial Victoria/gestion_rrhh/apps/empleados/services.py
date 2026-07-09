"""Escritura de empleados: reglas de negocio + transacción (§11-12).

R1  — única relación laboral ACTIVA por (empleado, empresa).
R10 — baja = finalizar relación (fecha + motivo); nunca DELETE físico.
El error amigable de R1 se valida acá (además del índice único en DB).
"""
from django.db import transaction
from rest_framework.exceptions import ValidationError

from .models import DocumentoEmpleado, Empleado, EstadoRelacion, RelacionLaboral


@transaction.atomic
def crear_empleado(*, actor, datos_empleado: dict, datos_relacion: dict) -> Empleado:
    """Alta de empleado + su relación laboral ACTIVA en la misma transacción (spec §1.1)."""
    empleado = Empleado.objects.create(creado_por=actor, **datos_empleado)
    crear_relacion_laboral(actor=actor, empleado=empleado, **datos_relacion)
    return empleado


@transaction.atomic
def actualizar_empleado(*, actor, empleado: Empleado, datos_empleado: dict) -> Empleado:
    for campo, valor in datos_empleado.items():
        setattr(empleado, campo, valor)
    empleado.save()
    return empleado


@transaction.atomic
def crear_relacion_laboral(
    *, actor, empleado: Empleado, estado: str = EstadoRelacion.ACTIVA, **datos
) -> RelacionLaboral:
    empresa = datos.get("empresa")
    if estado == EstadoRelacion.ACTIVA and RelacionLaboral.objects.filter(
        empleado=empleado, empresa=empresa, estado=EstadoRelacion.ACTIVA
    ).exists():
        # R1: error amigable antes de que salte el índice único parcial.
        raise ValidationError(
            {"empresa": "El empleado ya tiene una relación laboral activa en esta empresa."}
        )
    return RelacionLaboral.objects.create(
        creado_por=actor, empleado=empleado, estado=estado, **datos
    )


@transaction.atomic
def finalizar_relacion(
    *, actor, relacion: RelacionLaboral, fecha_egreso, motivo_egreso: str
) -> RelacionLaboral:
    """R10: baja lógica. Finaliza la relación con fecha y motivo; no borra nada."""
    if relacion.estado != EstadoRelacion.ACTIVA:
        raise ValidationError({"estado": "La relación laboral ya está finalizada."})
    if relacion.fecha_ingreso and fecha_egreso < relacion.fecha_ingreso:
        raise ValidationError(
            {"fecha_egreso": "La fecha de egreso no puede ser anterior al ingreso."}
        )
    relacion.estado = EstadoRelacion.FINALIZADA
    relacion.fecha_egreso = fecha_egreso
    relacion.motivo_egreso = motivo_egreso
    relacion.save(update_fields=["estado", "fecha_egreso", "motivo_egreso", "actualizado_en"])
    return relacion


@transaction.atomic
def crear_documento(*, actor, empleado: Empleado, **datos) -> DocumentoEmpleado:
    tipo_documento = datos.get("tipo_documento")
    if DocumentoEmpleado.objects.filter(
        empleado=empleado, tipo_documento=tipo_documento
    ).exists():
        raise ValidationError(
            {"tipo_documento": "El empleado ya tiene un documento vigente de este tipo."}
        )
    return DocumentoEmpleado.objects.create(creado_por=actor, empleado=empleado, **datos)
