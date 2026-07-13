"""Escritura de novedades: reglas de negocio + transacción (§6 bis, §11-12).

Las transiciones de estado NO se hacen por PATCH: cada una es un service dedicado con su
regla (R11: aprobar/rechazar exige rol RRHH/Admin, se valida en la capa de permisos). La
cadena de prórrogas concentra RP1–RP7 en `prorrogar_novedad`, todo transaccional.

TODO(RP8): registrar cada eslabón (creación, aprobación, rechazo, anulación, prórroga) en
RegistroAuditoria con acción semántica cuando exista la app `auditoria` (hoy no existe;
`empleados` tampoco audita todavía).
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from . import selectors
from .models import EstadoNovedad, Novedad

# Estados desde los que una novedad todavía puede editarse o resolverse.
_ABIERTOS = (EstadoNovedad.REGISTRADA, EstadoNovedad.EN_PROCESO)


@transaction.atomic
def crear_novedad(*, actor, datos: dict) -> Novedad:
    """Alta manual de una novedad (R12: la forma la validó el serializer; acá la consistencia)."""
    tipo = datos["tipo_novedad"]
    empleado = datos["empleado"]
    fecha_hasta = datos.get("fecha_hasta")

    if not empleado.activo:
        # No se cargan novedades nuevas sobre un empleado dado de baja (sin relación ACTIVA).
        # Las novedades históricas (cargadas cuando estaba activo) se conservan.
        raise ValidationError(
            {"empleado": "No se pueden registrar novedades de un empleado dado de baja."}
        )
    if tipo.requiere_cantidad_horas and datos.get("cantidad_horas") is None:
        raise ValidationError(
            {"cantidad_horas": f"El tipo '{tipo.nombre}' requiere la cantidad de horas."}
        )
    if fecha_hasta and fecha_hasta < datos["fecha_desde"]:
        raise ValidationError(
            {"fecha_hasta": "La fecha de fin no puede ser anterior al inicio."}
        )
    if not datos.get("relacion_laboral"):
        datos["relacion_laboral"] = empleado.relacion_activa
    return Novedad.objects.create(creado_por=actor, **datos)


@transaction.atomic
def actualizar_novedad(*, actor, novedad: Novedad, datos: dict) -> Novedad:
    """Edición solo mientras está REGISTRADA (§8): una vez en proceso o resuelta, es inmutable."""
    if novedad.estado != EstadoNovedad.REGISTRADA:
        raise ValidationError(
            {"estado": "Solo se puede editar una novedad en estado Registrada."}
        )
    for campo, valor in datos.items():
        setattr(novedad, campo, valor)
    novedad.save()
    return novedad


@transaction.atomic
def aprobar_novedad(*, actor, novedad: Novedad) -> Novedad:
    """R11: solo las APROBADAS justifican jornadas; aprobar exige rol RRHH/Admin (permisos)."""
    if novedad.estado not in _ABIERTOS:
        raise ValidationError(
            {"estado": f"No se puede aprobar una novedad {novedad.get_estado_display()}."}
        )
    novedad.estado = EstadoNovedad.APROBADA
    novedad.aprobada_por = actor
    novedad.aprobada_en = timezone.now()
    novedad.save(
        update_fields=["estado", "aprobada_por", "aprobada_en", "actualizado_en"]
    )
    return novedad


@transaction.atomic
def rechazar_novedad(*, actor, novedad: Novedad, motivo: str = "") -> Novedad:
    if novedad.estado not in _ABIERTOS:
        raise ValidationError(
            {"estado": f"No se puede rechazar una novedad {novedad.get_estado_display()}."}
        )
    novedad.estado = EstadoNovedad.RECHAZADA
    if motivo:
        novedad.observaciones = f"{novedad.observaciones}\nRechazo: {motivo}".strip()
    novedad.save(update_fields=["estado", "observaciones", "actualizado_en"])
    return novedad


@transaction.atomic
def anular_novedad(*, actor, novedad: Novedad, motivo: str = "") -> Novedad:
    """RP6: anular una prórroga no toca la cadena. Anular la MADRE con prórrogas activas
    está bloqueado: hay que anular cada prórroga (o la cadena) explícitamente.
    """
    if novedad.estado == EstadoNovedad.ANULADA:
        raise ValidationError({"estado": "La novedad ya está anulada."})
    if not novedad.es_prorroga:
        tiene_prorrogas_activas = novedad.prorrogas.exclude(
            estado=EstadoNovedad.ANULADA
        ).exists()
        if tiene_prorrogas_activas:
            raise ValidationError(
                {
                    "estado": "No se puede anular la novedad madre con prórrogas activas. "
                    "Anulá primero cada prórroga."
                }
            )
    novedad.estado = EstadoNovedad.ANULADA
    if motivo:
        novedad.observaciones = f"{novedad.observaciones}\nAnulación: {motivo}".strip()
    novedad.save(update_fields=["estado", "observaciones", "actualizado_en"])
    return novedad


def _hay_solapamiento_aprobado(*, empleado, desde, hasta, madre_id) -> bool:
    """RP4: ¿el rango [desde, hasta] pisa OTRA novedad aprobada del empleado que justifique
    ausencia? Se excluye la propia cadena (madre + sus prórrogas).
    """
    hasta = hasta or desde
    candidatas = (
        Novedad.objects.filter(
            empleado=empleado,
            estado=EstadoNovedad.APROBADA,
            tipo_novedad__justifica_ausencia=True,
        )
        .exclude(pk=madre_id)
        .exclude(novedad_origen_id=madre_id)
    )
    for otra in candidatas:
        otra_hasta = otra.fecha_hasta or otra.fecha_desde
        if otra.fecha_desde <= hasta and desde <= otra_hasta:
            return True
    return False


@transaction.atomic
def prorrogar_novedad(
    *, actor, novedad: Novedad, fecha_hasta_nueva, motivo: str = "", certificado_recibido_en=None
) -> Novedad:
    """Crea una prórroga en la cadena (§6 bis). Concentra RP1–RP7.

    Si `novedad` es una prórroga, la operación se redirige a la madre (el cliente no necesita
    saber cuál es). La prórroga nace REGISTRADA (RP5), hereda el tipo de la madre (RP7) y su
    `fecha_desde` se calcula contigua a la vigencia efectiva actual (RP3, por construcción).
    """
    madre = selectors.novedad_madre(novedad)  # redirección a la madre
    tipo = madre.tipo_novedad

    if not tipo.admite_prorroga:  # RP2
        raise ValidationError(
            {"tipo_novedad": f"El tipo '{tipo.nombre}' no admite prórrogas."}
        )
    if madre.estado != EstadoNovedad.APROBADA:  # RP2 (no se prorroga algo no aprobado)
        raise ValidationError(
            {"estado": "Solo se prorroga una novedad aprobada."}
        )

    vig = selectors.vigencia_efectiva(madre)
    hasta_actual = vig["hasta"]
    if hasta_actual is None:
        raise ValidationError(
            {"fecha_hasta": "La licencia no tiene fecha de fin definida; no se puede prorrogar."}
        )
    if fecha_hasta_nueva <= hasta_actual:  # RP3: la prórroga tiene que extender de verdad
        raise ValidationError(
            {
                "fecha_hasta_nueva": f"La nueva fecha de fin debe ser posterior a la "
                f"vigencia actual ({hasta_actual.isoformat()})."
            }
        )

    nueva_desde = hasta_actual + timedelta(days=1)  # RP3: contigua a la cadena
    if _hay_solapamiento_aprobado(
        empleado=madre.empleado, desde=nueva_desde, hasta=fecha_hasta_nueva, madre_id=madre.id
    ):  # RP4
        raise ValidationError(
            {"fecha_hasta_nueva": "El período se solapa con otra novedad aprobada del empleado."}
        )

    return Novedad.objects.create(
        creado_por=actor,
        empleado=madre.empleado,
        relacion_laboral=madre.relacion_laboral,
        tipo_novedad=tipo,  # RP7: hereda el tipo
        fecha_desde=nueva_desde,
        fecha_hasta=fecha_hasta_nueva,
        motivo=motivo,
        certificado_recibido_en=certificado_recibido_en,
        novedad_origen=madre,  # apunta SIEMPRE a la madre
        estado=EstadoNovedad.REGISTRADA,  # RP5: nace pendiente
    )
