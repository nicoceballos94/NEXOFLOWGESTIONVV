"""Escritura de novedades: reglas de negocio + transacción (§6 bis, §11-12).

Las transiciones de estado NO se hacen por PATCH: cada una es un service dedicado con su
regla (R11: aprobar/rechazar exige rol RRHH/Admin, se valida en la capa de permisos). La
cadena de prórrogas concentra RP1–RP7 en `prorrogar_novedad`, todo transaccional.

RP8 (auditoría): cada eslabón de la vida de una novedad se asienta en la bitácora con una
acción semántica —`NOVEDAD_RECHAZADA` cuenta una historia, un diff `estado: … → …` no—.
Los eventos de la CADENA (prórrogas, adjuntos) se asientan sobre la **madre**: la cadena es
un solo período y su historia se lee en un solo lugar.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.auditoria.services import Accion, registrar_evento, tomar_foto
from apps.empleados.models import Empleado, EstadoRelacion, RelacionLaboral
from common import roles
from common.permissions import usuario_tiene_rol
from common.storage import borrar_archivo_al_confirmar

from . import selectors
from .confidencialidad import CAMPOS_CONFIDENCIALES_NOVEDAD
from .models import (
    OCUPAN_PERIODO,
    AdjuntoNovedad,
    EstadoNovedad,
    Novedad,
    TipoNovedad,
)

# Estados desde los que una novedad todavía puede editarse o resolverse.
_ABIERTOS = (EstadoNovedad.REGISTRADA, EstadoNovedad.EN_PROCESO)
_FECHA_NO_INFORMADA = object()


def _fin_normalizado(*, tipo, fecha_desde, fecha_hasta):
    """Una FALTA sin fin explícito representa únicamente el día informado.

    Los demás tipos con fin nulo sí son rangos abiertos (por ejemplo, una licencia
    médica todavía sin alta). Mantener ambas semánticas separadas evita que una falta
    de un día bloquee indefinidamente el calendario del empleado.
    """
    if tipo.codigo == "FALTA" and fecha_hasta is None:
        return fecha_desde
    return fecha_hasta


def _validar_fechas_seguimiento(
    *,
    fecha_desde,
    fecha_hasta=None,
    fecha_turno_praxis=None,
    fecha_fin_estimada=None,
    fecha_reintegro=None,
    certificado_recibido_en=None,
) -> None:
    """Valida la cronología de los hitos médicos sobre el período resultante."""
    errores = {}
    for campo, valor in (
        ("fecha_turno_praxis", fecha_turno_praxis),
        ("fecha_fin_estimada", fecha_fin_estimada),
        ("fecha_reintegro", fecha_reintegro),
    ):
        if valor is not None and valor < fecha_desde:
            errores[campo] = "La fecha de seguimiento no puede ser anterior al inicio."
    if (
        fecha_reintegro is not None
        and fecha_hasta is not None
        and fecha_reintegro <= fecha_hasta
    ):
        errores["fecha_reintegro"] = (
            "La fecha de reintegro debe ser posterior al fin de la novedad."
        )
    if (
        certificado_recibido_en is not None
        and certificado_recibido_en > timezone.localdate()
    ):
        errores["certificado_recibido_en"] = (
            "La fecha de recepción del certificado no puede estar en el futuro."
        )
    if errores:
        raise ValidationError(errores)


def _tomar_calendario(empleado) -> None:
    """Serializa las escrituras de novedades del mismo empleado dentro de la transacción.

    `_validar_sin_solapamiento` es un SELECT seguido de un INSERT: sin esto, dos requests
    concurrentes pasan ambas la validación y crean novedades solapadas. El lock sobre la
    fila del empleado los pone en fila y hace que la segunda vea a la primera ya escrita,
    de modo que la carrera muera con el mensaje amigable del service y no con el
    IntegrityError del ExclusionConstraint (que es la red de seguridad, no la puerta).
    """
    Empleado.objects.select_for_update().filter(pk=empleado.pk).first()


def _bloquear_novedad_y_madre(novedad: Novedad) -> tuple[Novedad, Novedad]:
    """Relee bajo lock en el orden persona → relación → novedad/cadena.

    Ese orden coincide con alta, baja y reasignación de supervisor. Además de evitar
    decisiones sobre una asignación obsoleta, reduce los deadlocks entre una transición
    de novedad y una baja/reasignación concurrente.
    """

    Empleado.objects.select_for_update().get(pk=novedad.empleado_id)
    relacion = (
        RelacionLaboral.objects.select_for_update(of=("self",))
        .select_related("supervisor")
        .get(pk=novedad.relacion_laboral_id)
    )
    madre_id = novedad.novedad_origen_id or novedad.pk
    base = Novedad.objects.select_for_update(of=("self",)).select_related(
        "empleado", "relacion_laboral", "tipo_novedad", "novedad_origen"
    )
    madre = base.get(pk=madre_id)
    madre.relacion_laboral = relacion
    if novedad.pk == madre_id:
        return madre, madre
    eslabon = base.get(pk=novedad.pk)
    eslabon.relacion_laboral = relacion
    return eslabon, madre


def _validar_alcance_de_supervisor(*, actor, relacion: RelacionLaboral) -> None:
    """Un Supervisor puro solo opera relaciones que tiene asignadas.

    La vista ya recorta objetos visibles, pero el alta no parte de un queryset y una
    reasignación puede ocurrir entre la lectura y la escritura. Esta comprobación vive en
    el service y se ejecuta con persona/relación bloqueadas.
    """

    if usuario_tiene_rol(actor, (roles.ADMIN, roles.RRHH)):
        return
    if (
        usuario_tiene_rol(actor, (roles.SUPERVISOR,))
        and relacion.supervisor_id != actor.pk
    ):
        raise PermissionDenied(
            "Un Supervisor solo puede operar empleados que tiene asignados."
        )


def _validar_campos_editables_por_supervisor(*, actor, datos: dict) -> None:
    """Evita que un rol con lectura redactada sobrescriba datos que no puede ver."""

    if usuario_tiene_rol(actor, (roles.ADMIN, roles.RRHH)):
        return
    if usuario_tiene_rol(actor, (roles.SUPERVISOR,)):
        confidenciales = sorted(CAMPOS_CONFIDENCIALES_NOVEDAD.intersection(datos))
        if confidenciales:
            raise PermissionDenied(
                "Un Supervisor no puede modificar campos médicos o confidenciales."
            )


def _validar_relacion_de_novedad(
    *,
    empleado,
    relacion,
    fecha_desde,
    fecha_hasta=None,
    exigir_activa: bool,
) -> None:
    if relacion is None:
        raise ValidationError(
            {"relacion_laboral": "El empleado no tiene una relación laboral activa."}
        )
    if relacion.empleado_id != empleado.pk:
        raise ValidationError(
            {"relacion_laboral": "La relación laboral no pertenece al empleado indicado."}
        )
    if exigir_activa and relacion.estado != EstadoRelacion.ACTIVA:
        raise ValidationError(
            {"relacion_laboral": "Solo se registran novedades sobre la relación activa."}
        )
    if fecha_desde < relacion.fecha_ingreso:
        raise ValidationError(
            {
                "fecha_desde": "La novedad no puede comenzar antes del ingreso de la "
                "relación laboral."
            }
        )
    if relacion.fecha_egreso is not None:
        if fecha_desde > relacion.fecha_egreso:
            raise ValidationError(
                {
                    "fecha_desde": (
                        "La novedad no puede comenzar después del egreso de la relación "
                        "laboral."
                    )
                }
            )
        if fecha_hasta is None or fecha_hasta > relacion.fecha_egreso:
            raise ValidationError(
                {
                    "fecha_hasta": (
                        "La novedad debe terminar dentro de la vigencia de la relación "
                        "laboral."
                    )
                }
            )


def _filtro_solapadas_con(desde, hasta) -> Q:
    """Q que matchea las novedades cuyo rango pisa [desde, hasta], ambos extremos inclusive.

    Es el mismo predicado que evalúa el ExclusionConstraint con `daterange(..., '[]') &&`,
    escrito en ORM para poder usarlo como filtro: dos rangos se pisan si ninguno termina
    antes de que el otro empiece.

    `hasta`/`fecha_hasta` en None = rango abierto (licencia sin alta médica): corre sin fin,
    así que pisa todo lo que empiece en o después de su `desde`. Vale para los dos lados, y
    por eso el `isnull=True` va explícito: en SQL, `fecha_hasta >= x` con NULL da desconocido
    (o sea, no matchea) y las novedades abiertas se escaparían del filtro.
    """
    solapan = Q(fecha_hasta__isnull=True) | Q(fecha_hasta__gte=desde)
    if hasta is not None:
        solapan &= Q(fecha_desde__lte=hasta)
    return solapan


def _ids_de_la_cadena(novedad: Novedad) -> set:
    """Madre + prórrogas: una cadena es un solo período, nunca se solapa consigo misma."""
    madre = selectors.novedad_madre(novedad)
    return {madre.id, *madre.prorrogas.values_list("id", flat=True)}


def _validar_sin_solapamiento(
    *, empleado, tipo, desde, hasta, excluir_ids=(), campo="fecha_desde"
):
    """Regla: un empleado no puede tener dos novedades ocupando el mismo período.

    Falta, licencia, accidente, vacaciones y permiso se excluyen entre sí (todos los tipos
    con `ocupa_periodo`); las horas extra conviven con lo que haya. Solo cuentan las
    novedades en `OCUPAN_PERIODO`: rechazar o anular la anterior libera las fechas.

    Esta es la puerta (mensaje amigable); el ExclusionConstraint del modelo es la red de
    seguridad. Las dos miran las mismas columnas y los mismos estados a propósito.

    El solapamiento se filtra en SQL y no descartando en Python: así Postgres resuelve el
    rango con el índice GiST que ya trae el ExclusionConstraint —sobre (empleado_id,
    daterange(fecha_desde, fecha_hasta))— en vez de traer el historial entero del empleado
    para tirar casi todo. Con años de novedades por persona, la diferencia importa.
    """
    if not tipo.ocupa_periodo:
        return
    otra = (
        Novedad.objects.filter(
            _filtro_solapadas_con(desde, hasta),
            empleado=empleado,
            estado__in=OCUPAN_PERIODO,
            ocupa_periodo=True,  # la columna propia, la misma que mira el ExclusionConstraint
        )
        .exclude(pk__in=excluir_ids or [])
        .select_related("tipo_novedad")
        .first()  # la más reciente por el orden del Meta; si hay varias, alcanza con una
    )
    if otra is None:
        return
    fin = otra.fecha_hasta.isoformat() if otra.fecha_hasta else "sin fin"
    raise ValidationError(
        {
            campo: (
                f"El empleado ya tiene una novedad en ese período: "
                f"{otra.tipo_novedad.nombre} "
                f"({otra.fecha_desde.isoformat()} → {fin}, {otra.get_estado_display()}). "
                f"Dos novedades no pueden convivir en las mismas fechas: corregí el "
                f"período, o rechazá/anulá la anterior."
            )
        }
    )


@transaction.atomic
def crear_novedad(*, actor, datos: dict) -> Novedad:
    """Alta manual de una novedad (R12: la forma la validó el serializer; acá la consistencia)."""
    tipo = datos["tipo_novedad"]
    empleado = datos["empleado"]
    fecha_hasta = _fin_normalizado(
        tipo=tipo,
        fecha_desde=datos["fecha_desde"],
        fecha_hasta=datos.get("fecha_hasta"),
    )
    datos["fecha_hasta"] = fecha_hasta

    _tomar_calendario(empleado)
    tipo = TipoNovedad.objects.select_for_update().get(pk=tipo.pk)
    datos["tipo_novedad"] = tipo
    if not tipo.activo:
        raise ValidationError({"tipo_novedad": "El tipo de novedad está inactivo."})

    relacion_activa = (
        RelacionLaboral.objects.select_for_update(of=("self",))
        .select_related("empleado", "supervisor")
        .filter(empleado=empleado, estado=EstadoRelacion.ACTIVA)
        .first()
    )
    relacion_informada = datos.get("relacion_laboral")
    if relacion_informada and relacion_activa != relacion_informada:
        raise ValidationError(
            {"relacion_laboral": "Debe seleccionarse la relación laboral activa del empleado."}
        )
    relacion = relacion_activa
    _validar_relacion_de_novedad(
        empleado=empleado,
        relacion=relacion,
        fecha_desde=datos["fecha_desde"],
        fecha_hasta=fecha_hasta,
        exigir_activa=True,
    )
    _validar_alcance_de_supervisor(actor=actor, relacion=relacion)

    cantidad_horas = datos.get("cantidad_horas")
    if tipo.requiere_cantidad_horas and cantidad_horas is None:
        raise ValidationError(
            {"cantidad_horas": f"El tipo '{tipo.nombre}' requiere la cantidad de horas."}
        )
    if cantidad_horas is not None and cantidad_horas <= 0:
        raise ValidationError({"cantidad_horas": "La cantidad de horas debe ser mayor que cero."})
    if not tipo.requiere_cantidad_horas and cantidad_horas is not None:
        raise ValidationError(
            {"cantidad_horas": f"El tipo '{tipo.nombre}' no admite cantidad de horas."}
        )
    if fecha_hasta and fecha_hasta < datos["fecha_desde"]:
        raise ValidationError(
            {"fecha_hasta": "La fecha de fin no puede ser anterior al inicio."}
        )
    _validar_fechas_seguimiento(
        fecha_desde=datos["fecha_desde"],
        fecha_hasta=fecha_hasta,
        fecha_turno_praxis=datos.get("fecha_turno_praxis"),
        fecha_fin_estimada=datos.get("fecha_fin_estimada"),
        fecha_reintegro=datos.get("fecha_reintegro"),
        certificado_recibido_en=datos.get("certificado_recibido_en"),
    )
    # RP4 extendida al alta: no se carga una novedad sobre otra que ya ocupa el período.
    _validar_sin_solapamiento(
        empleado=empleado, tipo=tipo, desde=datos["fecha_desde"], hasta=fecha_hasta
    )
    datos["relacion_laboral"] = relacion
    novedad = Novedad.objects.create(creado_por=actor, **datos)
    registrar_evento(actor=actor, accion=Accion.NOVEDAD_CREADA, objeto=novedad)
    return novedad


def _rechazar_campos_de_la_cadena(novedad: Novedad, datos: dict) -> None:
    """Campos que una prórroga hereda por construcción y el cliente no puede tocar."""
    errores = {}
    entrante = datos.get("fecha_desde")
    if entrante is not None and entrante != novedad.fecha_desde:
        errores["fecha_desde"] = (
            "El inicio de una prórroga lo fija la cadena (arranca al día siguiente del fin "
            "de la vigencia anterior) y no se edita. Para correr el período, anulá la "
            "prórroga y volvé a prorrogar con las fechas correctas."
        )
    tipo_entrante = datos.get("tipo_novedad")
    if tipo_entrante is not None and tipo_entrante.pk != novedad.tipo_novedad_id:
        errores["tipo_novedad"] = (
            "Una prórroga hereda el tipo de la novedad madre y no se cambia (RP7)."
        )
    if errores:
        raise ValidationError(errores)


@transaction.atomic
def actualizar_novedad(*, actor, novedad: Novedad, datos: dict) -> Novedad:
    """Edición solo mientras está REGISTRADA (§8): una vez en proceso o resuelta, es inmutable.

    Las fechas se revalidan con las mismas reglas del alta: editar no puede meter la novedad
    encima de otra que ya ocupa el período. La propia cadena de prórrogas no cuenta.

    En una prórroga, `fecha_desde` y `tipo_novedad` no son datos de carga: los construye
    `prorrogar_novedad` (RP3 contigua a la cadena, RP7 heredando el tipo de la madre) y
    editarlos rompería la cadena — con el agravante de que la validación de solapamiento
    excluye a propósito los eslabones de la propia cadena y no lo detectaría.
    """
    novedad, madre = _bloquear_novedad_y_madre(novedad)
    _validar_alcance_de_supervisor(
        actor=actor,
        relacion=novedad.relacion_laboral,
    )
    _validar_campos_editables_por_supervisor(actor=actor, datos=datos)
    if novedad.estado != EstadoNovedad.REGISTRADA:
        raise ValidationError(
            {"estado": "Solo se puede editar una novedad en estado Registrada."}
        )
    if novedad.es_prorroga:
        _rechazar_campos_de_la_cadena(novedad, datos)
    _tomar_calendario(novedad.empleado)
    antes = tomar_foto(novedad)
    for campo, valor in datos.items():
        setattr(novedad, campo, valor)  # mezcla lo editado con lo que ya tenía
    novedad.tipo_novedad = TipoNovedad.objects.select_for_update().get(
        pk=novedad.tipo_novedad_id
    )
    novedad.fecha_hasta = _fin_normalizado(
        tipo=novedad.tipo_novedad,
        fecha_desde=novedad.fecha_desde,
        fecha_hasta=novedad.fecha_hasta,
    )
    if not novedad.tipo_novedad.activo:
        raise ValidationError({"tipo_novedad": "El tipo de novedad está inactivo."})
    if novedad.tipo_novedad.requiere_cantidad_horas:
        if novedad.cantidad_horas is None or novedad.cantidad_horas <= 0:
            raise ValidationError(
                {"cantidad_horas": "Este tipo requiere una cantidad de horas mayor que cero."}
            )
    elif novedad.cantidad_horas is not None:
        raise ValidationError(
            {"cantidad_horas": "Este tipo de novedad no admite cantidad de horas."}
        )
    if novedad.fecha_hasta and novedad.fecha_hasta < novedad.fecha_desde:
        raise ValidationError(
            {"fecha_hasta": "La fecha de fin no puede ser anterior al inicio."}
        )
    _validar_relacion_de_novedad(
        empleado=novedad.empleado,
        relacion=novedad.relacion_laboral,
        fecha_desde=novedad.fecha_desde,
        fecha_hasta=novedad.fecha_hasta,
        exigir_activa=False,
    )
    _validar_fechas_seguimiento(
        fecha_desde=novedad.fecha_desde,
        fecha_hasta=novedad.fecha_hasta,
        fecha_turno_praxis=novedad.fecha_turno_praxis,
        fecha_fin_estimada=novedad.fecha_fin_estimada,
        fecha_reintegro=novedad.fecha_reintegro,
        certificado_recibido_en=novedad.certificado_recibido_en,
    )
    _validar_sin_solapamiento(
        empleado=novedad.empleado,
        tipo=novedad.tipo_novedad,
        desde=novedad.fecha_desde,
        hasta=novedad.fecha_hasta,
        excluir_ids=_ids_de_la_cadena(novedad),
    )
    novedad.save()
    registrar_evento(
        actor=actor,
        accion=Accion.NOVEDAD_ACTUALIZADA,
        objeto=novedad,
        antes=antes,
        solo_si_cambia=True,
        agregado=madre,
    )
    return novedad


@transaction.atomic
def tomar_novedad(*, actor, novedad: Novedad) -> Novedad:
    """REGISTRADA → EN_PROCESO: un operativo deja constancia de que empezó a tratarla."""
    novedad, madre = _bloquear_novedad_y_madre(novedad)
    _validar_alcance_de_supervisor(
        actor=actor,
        relacion=novedad.relacion_laboral,
    )
    if novedad.estado != EstadoNovedad.REGISTRADA:
        raise ValidationError(
            {
                "estado": (
                    "Solo se puede tomar una novedad Registrada; "
                    f"la novedad está {novedad.get_estado_display()}."
                )
            }
        )
    _validar_relacion_de_novedad(
        empleado=novedad.empleado,
        relacion=novedad.relacion_laboral,
        fecha_desde=novedad.fecha_desde,
        fecha_hasta=novedad.fecha_hasta,
        exigir_activa=False,
    )
    antes = tomar_foto(novedad)
    novedad.estado = EstadoNovedad.EN_PROCESO
    novedad.tomada_por = actor
    novedad.tomada_en = timezone.now()
    novedad.save(
        update_fields=["estado", "tomada_por", "tomada_en", "actualizado_en"]
    )
    registrar_evento(
        actor=actor,
        accion=Accion.NOVEDAD_TOMADA,
        objeto=novedad,
        antes=antes,
        agregado=madre,
    )
    return novedad


@transaction.atomic
def aprobar_novedad(*, actor, novedad: Novedad) -> Novedad:
    """R11: solo las APROBADAS justifican jornadas; aprobar exige rol RRHH/Admin (permisos)."""
    novedad, madre = _bloquear_novedad_y_madre(novedad)
    if novedad.estado not in _ABIERTOS:
        raise ValidationError(
            {"estado": f"No se puede aprobar una novedad {novedad.get_estado_display()}."}
        )
    antes = tomar_foto(novedad)
    novedad.estado = EstadoNovedad.APROBADA
    novedad.aprobada_por = actor
    novedad.aprobada_en = timezone.now()
    novedad.save(
        update_fields=["estado", "aprobada_por", "aprobada_en", "actualizado_en"]
    )
    registrar_evento(
        actor=actor,
        accion=Accion.NOVEDAD_APROBADA,
        objeto=novedad,
        antes=antes,
        agregado=madre,
    )
    return novedad


@transaction.atomic
def cerrar_novedad(
    *,
    actor,
    novedad: Novedad,
    fecha_hasta=_FECHA_NO_INFORMADA,
) -> Novedad:
    """APROBADA → CERRADA, fijando atómicamente el fin si todavía estaba abierta."""
    novedad, madre = _bloquear_novedad_y_madre(novedad)
    _validar_alcance_de_supervisor(
        actor=actor,
        relacion=novedad.relacion_laboral,
    )
    if novedad.estado != EstadoNovedad.APROBADA:
        raise ValidationError(
            {
                "estado": (
                    "Solo se puede cerrar una novedad Aprobada; "
                    f"la novedad está {novedad.get_estado_display()}."
                )
            }
        )
    fecha_cierre = novedad.fecha_hasta
    if fecha_cierre is None:
        if fecha_hasta is _FECHA_NO_INFORMADA:
            raise ValidationError(
                {
                    "fecha_hasta": (
                        "Para cerrar una novedad abierta debés informar su fecha de fin."
                    )
                }
            )
        fecha_cierre = fecha_hasta
        if fecha_cierre < novedad.fecha_desde:
            raise ValidationError(
                {"fecha_hasta": "La fecha de fin no puede ser anterior al inicio."}
            )
        _validar_relacion_de_novedad(
            empleado=novedad.empleado,
            relacion=novedad.relacion_laboral,
            fecha_desde=novedad.fecha_desde,
            fecha_hasta=fecha_cierre,
            exigir_activa=False,
        )
    elif fecha_hasta is not _FECHA_NO_INFORMADA and fecha_hasta != fecha_cierre:
        raise ValidationError(
            {
                "fecha_hasta": (
                    "La novedad ya tiene una fecha de fin. Corregila antes de aprobar; "
                    "cerrar no modifica silenciosamente el período aprobado."
                )
            }
        )
    if novedad.pk == madre.pk:
        pendientes = madre.prorrogas.exclude(
            estado__in=(
                EstadoNovedad.CERRADA,
                EstadoNovedad.RECHAZADA,
                EstadoNovedad.ANULADA,
            )
        )
        if pendientes.exists():
            raise ValidationError(
                {
                    "estado": (
                        "No se puede cerrar la novedad madre mientras haya prórrogas "
                        "sin cerrar, rechazar o anular."
                    )
                }
            )
    antes = tomar_foto(novedad)
    novedad.fecha_hasta = fecha_cierre
    novedad.estado = EstadoNovedad.CERRADA
    novedad.cerrada_por = actor
    novedad.cerrada_en = timezone.now()
    novedad.save(
        update_fields=[
            "fecha_hasta",
            "estado",
            "cerrada_por",
            "cerrada_en",
            "actualizado_en",
        ]
    )
    registrar_evento(
        actor=actor,
        accion=Accion.NOVEDAD_CERRADA,
        objeto=novedad,
        antes=antes,
        agregado=madre,
    )
    return novedad


@transaction.atomic
def rechazar_novedad(*, actor, novedad: Novedad, motivo: str) -> Novedad:
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError({"motivo": "El motivo del rechazo es obligatorio."})
    novedad, madre = _bloquear_novedad_y_madre(novedad)
    if novedad.estado not in _ABIERTOS:
        raise ValidationError(
            {"estado": f"No se puede rechazar una novedad {novedad.get_estado_display()}."}
        )
    antes = tomar_foto(novedad)
    novedad.estado = EstadoNovedad.RECHAZADA
    novedad.motivo_rechazo = motivo
    novedad.rechazada_por = actor
    novedad.rechazada_en = timezone.now()
    novedad.save(
        update_fields=[
            "estado",
            "motivo_rechazo",
            "rechazada_por",
            "rechazada_en",
            "actualizado_en",
        ]
    )
    despues = tomar_foto(novedad)
    registrar_evento(
        actor=actor,
        accion=Accion.NOVEDAD_RECHAZADA,
        objeto=novedad,
        antes=antes,
        despues=despues,
        agregado=madre,
    )
    return novedad


@transaction.atomic
def anular_novedad(*, actor, novedad: Novedad, motivo: str) -> Novedad:
    """RP6: la cadena se anula de atrás hacia adelante para no fabricar huecos.

    Anular la MADRE con prórrogas activas está bloqueado: hay que anular cada prórroga
    explícitamente, empezando por la última.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError({"motivo": "El motivo de la anulación es obligatorio."})
    novedad, madre = _bloquear_novedad_y_madre(novedad)
    if novedad.estado == EstadoNovedad.ANULADA:
        raise ValidationError({"estado": "La novedad ya está anulada."})
    if novedad.pk == madre.pk:
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
    else:
        tiene_eslabones_posteriores = madre.prorrogas.filter(
            Q(fecha_desde__gt=novedad.fecha_desde)
            | Q(fecha_desde=novedad.fecha_desde, pk__gt=novedad.pk)
        ).exclude(estado=EstadoNovedad.ANULADA).exists()
        if tiene_eslabones_posteriores:
            raise ValidationError(
                {
                    "estado": (
                        "No se puede anular una prórroga intermedia. "
                        "Anulá primero los eslabones posteriores."
                    )
                }
            )
    antes = tomar_foto(novedad)
    novedad.estado = EstadoNovedad.ANULADA
    novedad.motivo_anulacion = motivo
    novedad.anulada_por = actor
    novedad.anulada_en = timezone.now()
    novedad.save(
        update_fields=[
            "estado",
            "motivo_anulacion",
            "anulada_por",
            "anulada_en",
            "actualizado_en",
        ]
    )
    despues = tomar_foto(novedad)
    registrar_evento(
        actor=actor,
        accion=Accion.NOVEDAD_ANULADA,
        objeto=novedad,
        antes=antes,
        despues=despues,
        agregado=madre,
    )
    return novedad


@transaction.atomic
def prorrogar_novedad(
    *, actor, novedad: Novedad, fecha_hasta_nueva, motivo: str = "", certificado_recibido_en=None
) -> Novedad:
    """Crea una prórroga en la cadena (§6 bis). Concentra RP1–RP7.

    Si `novedad` es una prórroga, la operación se redirige a la madre (el cliente no necesita
    saber cuál es). La prórroga nace REGISTRADA (RP5), hereda el tipo de la madre (RP7) y su
    `fecha_desde` se calcula contigua a la vigencia efectiva actual (RP3, por construcción).
    """
    _, madre = _bloquear_novedad_y_madre(novedad)
    _validar_alcance_de_supervisor(
        actor=actor,
        relacion=madre.relacion_laboral,
    )
    tipo = TipoNovedad.objects.select_for_update().get(
        pk=madre.tipo_novedad_id
    )
    madre.tipo_novedad = tipo

    _tomar_calendario(madre.empleado)
    if not tipo.activo:
        raise ValidationError({"tipo_novedad": "El tipo de novedad está inactivo."})
    if not tipo.admite_prorroga:  # RP2
        raise ValidationError(
            {"tipo_novedad": f"El tipo '{tipo.nombre}' no admite prórrogas."}
        )
    if madre.estado != EstadoNovedad.APROBADA:  # RP2 (no se prorroga algo no aprobado)
        raise ValidationError(
            {"estado": "Solo se prorroga una novedad aprobada."}
        )
    if madre.prorrogas.filter(estado__in=_ABIERTOS).exists():
        # `vigencia_efectiva` solo avanza con las prórrogas APROBADAS: prorrogar de nuevo
        # con una pendiente calcularía el mismo `nueva_desde` que la pendiente y crearía
        # dos eslabones pisados (la validación de solapamiento no lo ve, porque excluye la
        # cadena entera). La cadena avanza de a un eslabón resuelto por vez.
        raise ValidationError(
            {
                "estado": "La cadena ya tiene una prórroga pendiente de aprobación. "
                "Aprobala o rechazala antes de volver a prorrogar."
            }
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
    _validar_fechas_seguimiento(
        fecha_desde=nueva_desde,
        fecha_hasta=fecha_hasta_nueva,
        certificado_recibido_en=certificado_recibido_en,
    )
    _validar_relacion_de_novedad(
        empleado=madre.empleado,
        relacion=madre.relacion_laboral,
        fecha_desde=nueva_desde,
        fecha_hasta=fecha_hasta_nueva,
        exigir_activa=False,
    )
    _validar_sin_solapamiento(  # RP4
        empleado=madre.empleado,
        tipo=tipo,
        desde=nueva_desde,
        hasta=fecha_hasta_nueva,
        excluir_ids=_ids_de_la_cadena(madre),
        campo="fecha_hasta_nueva",
    )

    prorroga = Novedad.objects.create(
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
    # Se asienta sobre la MADRE, no sobre la prórroga: quien audita abre la licencia y
    # espera ver "se prorrogó hasta el 30/8" en su historia. Un evento colgado del eslabón
    # nuevo dejaría la madre sin rastro de que la cadena creció.
    registrar_evento(
        actor=actor,
        accion=Accion.NOVEDAD_PRORROGADA,
        objeto=madre,
        despues={
            "prorroga_id": prorroga.pk,
            "vigencia_anterior_hasta": hasta_actual.isoformat(),
            "prorrogada_hasta": fecha_hasta_nueva.isoformat(),
            "motivo": motivo,
        },
    )
    return prorroga


@transaction.atomic
def adjuntar_a_novedad(
    *, actor, novedad: Novedad, archivo, descripcion: str = ""
) -> AdjuntoNovedad:
    """Suma un respaldo a la bitácora de la novedad (certificado, estudio, radiografía).

    Se puede adjuntar en cualquier estado, incluso sobre una novedad ya cerrada o anulada:
    el certificado suele llegar días después del hecho, y una novedad anulada por error de
    carga puede necesitar el respaldo que prueba por qué se anuló. Restringirlo por estado
    obligaría a pelearle al sistema justo cuando aparece el papel que faltaba.

    Nada se pisa: cada adjunto se suma. Esa es la diferencia con el documento del empleado.
    """
    novedad, madre = _bloquear_novedad_y_madre(novedad)
    _validar_alcance_de_supervisor(
        actor=actor,
        relacion=novedad.relacion_laboral,
    )
    adjunto = AdjuntoNovedad(
        creado_por=actor,
        novedad=novedad,
        archivo=archivo,
        # `archivo.name` queda pisado por el upload_to (pasa a ser el UUID), así que el
        # nombre con el que se subió se captura ACÁ, antes de guardar.
        nombre_original=getattr(archivo, "name", "") or "archivo",
        descripcion=descripcion,
    )
    try:
        adjunto.save()
        registrar_evento(
            actor=actor,
            accion=Accion.ADJUNTO_AGREGADO,
            objeto=novedad,
            despues={"archivo": adjunto.nombre_original, "descripcion": descripcion},
            agregado=madre,
        )
    except Exception:
        # El storage no participa del rollback de Postgres. Si falla el INSERT o la
        # auditoría, se elimina el binario recién escrito antes de propagar el error.
        if adjunto.archivo:
            adjunto.archivo.delete(save=False)
        raise
    return adjunto


@transaction.atomic
def quitar_adjunto(*, actor, adjunto: AdjuntoNovedad) -> None:
    """Un adjunto cargado por error no es historia: se va, con binario y todo.

    Es un DELETE físico y está bien que lo sea — a diferencia de la novedad (que se anula
    para dejar rastro), un PDF subido a la novedad equivocada no documenta nada. Lo que la
    bitácora conserva son los adjuntos correctos.
    """
    novedad, madre = _bloquear_novedad_y_madre(adjunto.novedad)
    _validar_alcance_de_supervisor(
        actor=actor,
        relacion=novedad.relacion_laboral,
    )
    adjunto = AdjuntoNovedad.objects.select_for_update().get(pk=adjunto.pk)
    archivo = adjunto.archivo  # la referencia sobrevive al DELETE; el binario, no
    # Antes del delete, y sobre la novedad: es el único rastro de que ese papel existió.
    registrar_evento(
        actor=actor,
        accion=Accion.ADJUNTO_ELIMINADO,
        objeto=novedad,
        antes={"archivo": adjunto.nombre_original, "descripcion": adjunto.descripcion},
        despues={},
        agregado=madre,
    )
    adjunto.delete()
    borrar_archivo_al_confirmar(archivo)
