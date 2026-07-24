"""Escritura de empleados: reglas de negocio + transacción (§11-12).

R1  — única relación laboral ACTIVA por (empleado, empresa).
R10 — baja = finalizar relación (fecha + motivo); nunca DELETE físico.
El error amigable de R1 se valida acá (además del índice único en DB).
El legajo lo asigna el backend: es un número de la organización, no un dato de carga.
"""
from django.db import connection, transaction
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import Accion, registrar_evento, tomar_foto
from common.storage import borrar_archivo_al_confirmar

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
    registrar_evento(actor=actor, accion=Accion.EMPLEADO_CREADO, objeto=empleado)
    # La relación asienta su propio evento: son dos hechos, y la baja de mañana toca uno solo.
    crear_relacion_laboral(actor=actor, empleado=empleado, **datos_relacion)
    return empleado


@transaction.atomic
def actualizar_empleado(*, actor, empleado: Empleado, datos_empleado: dict) -> Empleado:
    antes = tomar_foto(empleado)
    for campo, valor in datos_empleado.items():
        setattr(empleado, campo, valor)
    empleado.save()
    registrar_evento(
        actor=actor,
        accion=Accion.EMPLEADO_ACTUALIZADO,
        objeto=empleado,
        antes=antes,
        solo_si_cambia=True,  # abrir la ficha y guardarla sin tocar nada no es un hecho
    )
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
    relacion = RelacionLaboral.objects.create(
        creado_por=actor, empleado=empleado, estado=estado, **datos
    )
    registrar_evento(actor=actor, accion=Accion.RELACION_CREADA, objeto=relacion)
    return relacion


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
    antes = tomar_foto(relacion)
    relacion.estado = EstadoRelacion.FINALIZADA
    relacion.fecha_egreso = fecha_egreso
    relacion.motivo_egreso = motivo_egreso
    relacion.save(update_fields=["estado", "fecha_egreso", "motivo_egreso", "actualizado_en"])
    # La baja es EL evento que se le va a pedir a esta bitácora en una disputa laboral.
    registrar_evento(
        actor=actor, accion=Accion.RELACION_FINALIZADA, objeto=relacion, antes=antes
    )
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
    documento = DocumentoEmpleado.objects.create(
        creado_por=actor, empleado=empleado, **datos
    )
    registrar_evento(actor=actor, accion=Accion.DOCUMENTO_CREADO, objeto=documento)
    return documento




@transaction.atomic
def actualizar_documento(*, actor, documento: DocumentoEmpleado, **datos) -> DocumentoEmpleado:
    """Corrección y renovación de un documento (número, vencimiento, archivo, observaciones).

    Sin esto, el UNIQUE (empleado, tipo_documento) convertía cualquier documento cargado en
    un callejón sin salida: no se podía ni corregir un vencimiento mal tipeado.

    Renovar (apto médico nuevo) es mover `fecha_vencimiento` y reemplazar el archivo: no se
    conserva el ARCHIVO anterior. Es deliberado y acordado — un carnet o un CNRT viejo es
    basura, no historia. Lo que sí queda desde RP8 es el rastro del cambio en la bitácora
    (qué vencimiento tenía antes, quién lo movió y cuándo), que es lo que se discute cuando
    alguien pregunta por qué figuraba vigente. El respaldo de un hecho puntual (el
    certificado de una licencia, los estudios de un accidente) no vive acá: pertenece a su
    novedad, que lo conserva sola porque las novedades no se borran nunca.

    El tipo no se edita: cambiar el tipo es otro documento (borrá este y cargá el correcto).
    """
    # La referencia al archivo viejo se guarda ANTES de pisar el campo: después de asignar
    # el nuevo, el viejo queda sin quien lo nombre y el binario huérfano en disco.
    archivo_viejo = None
    if "archivo" in datos and documento.archivo and datos["archivo"] != documento.archivo:
        archivo_viejo = documento.archivo
    antes = tomar_foto(documento)
    for campo, valor in datos.items():
        setattr(documento, campo, valor)
    documento.save()
    registrar_evento(
        actor=actor,
        accion=Accion.DOCUMENTO_ACTUALIZADO,
        objeto=documento,
        antes=antes,
        solo_si_cambia=True,
    )
    borrar_archivo_al_confirmar(archivo_viejo)
    return documento


@transaction.atomic
def guardar_foto_empleado(*, actor, empleado: Empleado, foto) -> Empleado:
    """Setea (o reemplaza) la foto de perfil. La anterior se borra al confirmar.

    Reemplazar deja el binario viejo sin quien lo nombre; se libera con la misma red que los
    documentos (`borrar_archivo_al_confirmar`), después del commit y no antes.
    """
    foto_vieja = empleado.foto if empleado.foto else None
    antes = tomar_foto(empleado, campos=("foto",))
    empleado.foto = foto
    empleado.save(update_fields=["foto", "actualizado_en"])
    # `campos` acota el diff a la foto: el resto de la ficha no cambió y sería ruido.
    registrar_evento(
        actor=actor,
        accion=Accion.EMPLEADO_FOTO_CAMBIADA,
        objeto=empleado,
        antes=antes,
        campos=("foto",),
    )
    if foto_vieja and foto_vieja != empleado.foto:
        borrar_archivo_al_confirmar(foto_vieja)
    return empleado


@transaction.atomic
def eliminar_foto_empleado(*, actor, empleado: Empleado) -> Empleado:
    """Quita la foto de perfil y borra el binario al confirmar."""
    foto = empleado.foto if empleado.foto else None
    antes = tomar_foto(empleado, campos=("foto",))
    empleado.foto = None
    empleado.save(update_fields=["foto", "actualizado_en"])
    registrar_evento(
        actor=actor,
        accion=Accion.EMPLEADO_FOTO_ELIMINADA,
        objeto=empleado,
        antes=antes,
        campos=("foto",),
    )
    borrar_archivo_al_confirmar(foto)
    return empleado


@transaction.atomic
def eliminar_documento(*, actor, documento: DocumentoEmpleado) -> None:
    """DELETE físico: un documento cargado por error no es un hecho del dominio que preservar
    (a diferencia de la relación laboral, R10). Libera el UNIQUE para recargarlo bien.

    Se lleva el archivo puesto: borrar la fila y dejar el binario sería peor que no borrar
    nada — quedaría un dato de salud en el disco sin ninguna fila que diga de quién es.
    """
    archivo = documento.archivo  # la referencia sobrevive al DELETE; el binario, no
    # Se asienta ANTES del delete: después, Django deja el objeto sin pk y la constancia
    # perdería de qué documento hablaba. Es el único rastro que va a quedar de él.
    registrar_evento(
        actor=actor,
        accion=Accion.DOCUMENTO_ELIMINADO,
        objeto=documento,
        antes=tomar_foto(documento),
        despues={},
    )
    documento.delete()
    borrar_archivo_al_confirmar(archivo)
