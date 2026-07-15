"""Escritura de empleados: reglas de negocio + transacción (§11-12).

R1  — única relación laboral ACTIVA por (empleado, empresa).
R10 — baja = finalizar relación (fecha + motivo); nunca DELETE físico.
El error amigable de R1 se valida acá (además del índice único en DB).
El legajo lo asigna el backend: es un número de la organización, no un dato de carga.
"""
from django.db import connection, transaction
from rest_framework.exceptions import ValidationError

from .models import DocumentoEmpleado, Empleado, EstadoRelacion, RelacionLaboral

# Clave del advisory lock que serializa la asignación de legajo (arbitraria pero fija).
_LOCK_LEGAJO = 4021


def _asignar_legajo() -> str:
    """Siguiente legajo libre, con formato de 4 dígitos ("0001", "0042"…).

    `max(numérico)+1` es una lectura seguida de una escritura: dos altas simultáneas leen el
    mismo máximo y chocan contra el UNIQUE con un error críptico. El advisory lock las pone
    en fila y se libera al cerrar la transacción. Se ignoran los legajos no numéricos que
    pudieran venir de una importación histórica: la serie sigue por los números.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_LEGAJO])
        cursor.execute(
            "SELECT COALESCE(MAX(legajo::bigint), 0) FROM empleados_empleado "
            "WHERE legajo ~ '^[0-9]+$'"
        )
        maximo = cursor.fetchone()[0]
    return f"{maximo + 1:04d}"


@transaction.atomic
def crear_empleado(*, actor, datos_empleado: dict, datos_relacion: dict) -> Empleado:
    """Alta de empleado + su relación laboral ACTIVA en la misma transacción (spec §1.1)."""
    empleado = Empleado.objects.create(
        creado_por=actor, legajo=_asignar_legajo(), **datos_empleado
    )
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
            {
                "tipo_documento": "El empleado ya tiene un documento vigente de este tipo. "
                "Para renovarlo, editá su vencimiento."
            }
        )
    return DocumentoEmpleado.objects.create(creado_por=actor, empleado=empleado, **datos)


@transaction.atomic
def actualizar_documento(*, actor, documento: DocumentoEmpleado, **datos) -> DocumentoEmpleado:
    """Corrección y renovación de un documento (número, vencimiento, observaciones).

    Sin esto, el UNIQUE (empleado, tipo_documento) convertía cualquier documento cargado en
    un callejón sin salida: no se podía ni corregir un vencimiento mal tipeado. Renovar un
    apto médico es hoy mover su `fecha_vencimiento`; no queda historial de la versión
    anterior — la decisión de versionar espera al módulo de documentos con archivos.
    El tipo no se edita: cambiar el tipo es otro documento (borrá este y cargá el correcto).
    """
    for campo, valor in datos.items():
        setattr(documento, campo, valor)
    documento.save()
    return documento


@transaction.atomic
def eliminar_documento(*, actor, documento: DocumentoEmpleado) -> None:
    """DELETE físico: un documento cargado por error no es un hecho del dominio que preservar
    (a diferencia de la relación laboral, R10). Libera el UNIQUE para recargarlo bien.
    """
    documento.delete()
