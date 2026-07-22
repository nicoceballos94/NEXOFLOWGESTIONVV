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
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.empleados.models import Empleado
from common.storage import borrar_archivo_al_confirmar

from . import selectors
from .models import OCUPAN_PERIODO, AdjuntoNovedad, EstadoNovedad, Novedad

# Estados desde los que una novedad todavía puede editarse o resolverse.
_ABIERTOS = (EstadoNovedad.REGISTRADA, EstadoNovedad.EN_PROCESO)


def _tomar_calendario(empleado) -> None:
    """Serializa las escrituras de novedades del mismo empleado dentro de la transacción.

    `_validar_sin_solapamiento` es un SELECT seguido de un INSERT: sin esto, dos requests
    concurrentes pasan ambas la validación y crean novedades solapadas. El lock sobre la
    fila del empleado los pone en fila y hace que la segunda vea a la primera ya escrita,
    de modo que la carrera muera con el mensaje amigable del service y no con el
    IntegrityError del ExclusionConstraint (que es la red de seguridad, no la puerta).
    """
    Empleado.objects.select_for_update().filter(pk=empleado.pk).first()


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
    fecha_hasta = datos.get("fecha_hasta")

    _tomar_calendario(empleado)
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
    # RP4 extendida al alta: no se carga una novedad sobre otra que ya ocupa el período.
    _validar_sin_solapamiento(
        empleado=empleado, tipo=tipo, desde=datos["fecha_desde"], hasta=fecha_hasta
    )
    if not datos.get("relacion_laboral"):
        datos["relacion_laboral"] = empleado.relacion_activa
    return Novedad.objects.create(creado_por=actor, **datos)


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
    if novedad.estado != EstadoNovedad.REGISTRADA:
        raise ValidationError(
            {"estado": "Solo se puede editar una novedad en estado Registrada."}
        )
    if novedad.es_prorroga:
        _rechazar_campos_de_la_cadena(novedad, datos)
    _tomar_calendario(novedad.empleado)
    for campo, valor in datos.items():
        setattr(novedad, campo, valor)  # mezcla lo editado con lo que ya tenía
    if novedad.fecha_hasta and novedad.fecha_hasta < novedad.fecha_desde:
        raise ValidationError(
            {"fecha_hasta": "La fecha de fin no puede ser anterior al inicio."}
        )
    _validar_sin_solapamiento(
        empleado=novedad.empleado,
        tipo=novedad.tipo_novedad,
        desde=novedad.fecha_desde,
        hasta=novedad.fecha_hasta,
        excluir_ids=_ids_de_la_cadena(novedad),
    )
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

    _tomar_calendario(madre.empleado)
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
    _validar_sin_solapamiento(  # RP4
        empleado=madre.empleado,
        tipo=tipo,
        desde=nueva_desde,
        hasta=fecha_hasta_nueva,
        excluir_ids=_ids_de_la_cadena(madre),
        campo="fecha_hasta_nueva",
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
    adjunto = AdjuntoNovedad.objects.create(
        creado_por=actor,
        novedad=novedad,
        archivo=archivo,
        # `archivo.name` queda pisado por el upload_to (pasa a ser el UUID), así que el
        # nombre con el que se subió se captura ACÁ, antes de guardar.
        nombre_original=getattr(archivo, "name", "") or "archivo",
        descripcion=descripcion,
    )
    return adjunto


@transaction.atomic
def quitar_adjunto(*, actor, adjunto: AdjuntoNovedad) -> None:
    """Un adjunto cargado por error no es historia: se va, con binario y todo.

    Es un DELETE físico y está bien que lo sea — a diferencia de la novedad (que se anula
    para dejar rastro), un PDF subido a la novedad equivocada no documenta nada. Lo que la
    bitácora conserva son los adjuntos correctos.
    """
    archivo = adjunto.archivo  # la referencia sobrevive al DELETE; el binario, no
    adjunto.delete()
    borrar_archivo_al_confirmar(archivo)
