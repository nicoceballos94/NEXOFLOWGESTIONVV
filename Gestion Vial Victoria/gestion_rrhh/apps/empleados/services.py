"""Escritura de empleados: reglas de negocio + transacción (§11-12).

R1  — única relación laboral ACTIVA por empleado en todo el grupo.
R10 — baja = finalizar relación (fecha + motivo); nunca DELETE físico.
Las vigencias de una persona no se solapan y toda alta usa catálogos activos/coherentes.
Los errores amigables se validan acá y las constraints de DB contienen cualquier carrera.
El legajo lo asigna el backend: es un número de la organización, no un dato de carga.
"""
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import Accion, registrar_evento, tomar_foto
from apps.organizacion.models import Empresa, Puesto, Sector
from apps.usuarios.models import Usuario
from common import roles
from common.storage import borrar_archivo_al_confirmar

from .models import (
    DocumentoEmpleado,
    Empleado,
    EstadoRelacion,
    MotivoEgreso,
    RelacionLaboral,
    TipoDocumento,
)

# Clave del advisory lock que serializa la asignación de legajo (arbitraria pero fija).
_LOCK_LEGAJO = 4021

_CONSTRAINT_ACTIVA = "uniq_relacion_activa_por_empleado"
_CONSTRAINT_SOLAPADA = "excl_relaciones_solapadas_por_empleado"
_CONSTRAINT_FECHAS = "relacion_fechas_validas"
_CONSTRAINT_CATALOGOS = "relacion_activa_con_catalogos"
_CONSTRAINT_ESTADO_BAJA = "relacion_estado_baja_coherente"
_CONSTRAINT_DOCUMENTO_UNICO = "uniq_documento_por_relacion_tipo"
_CONSTRAINT_DOCUMENTO_RELACION = "documento_relacion_requerida"
_CONSTRAINT_IDENTIFICADORES = {
    "empleados_empleado_dni_key": (
        "dni",
        "Ya existe un empleado con ese DNI.",
    ),
    "empleados_empleado_cuil_key": (
        "cuil",
        "Ya existe un empleado con ese CUIL.",
    ),
    "empleados_empleado_id_huella_key": (
        "id_huella",
        "Ya existe un empleado con ese identificador de huella.",
    ),
    "empleados_empleado_usuario_id_key": (
        "usuario",
        "Ese usuario ya está vinculado a otro empleado.",
    ),
    "empleados_empleado_legajo_key": (
        "legajo",
        "No se pudo asignar un legajo único; reintentá la operación.",
    ),
}


def _motivo_egreso_valido(valor) -> str:
    motivo = str(valor or "").strip()
    if not motivo:
        raise ValidationError(
            {"motivo_egreso": "El motivo de egreso es obligatorio."}
        )
    if motivo not in MotivoEgreso.values:
        raise ValidationError(
            {"motivo_egreso": "El motivo de egreso no pertenece al catálogo permitido."}
        )
    return motivo


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


def _nombre_constraint(error: IntegrityError) -> str:
    causa = getattr(error, "__cause__", None)
    diag = getattr(causa, "diag", None)
    return getattr(diag, "constraint_name", "") or ""


def _traducir_integridad_relacion(error: IntegrityError) -> None:
    """Convierte únicamente constraints conocidas; un fallo ajeno sigue siendo visible."""
    nombre = _nombre_constraint(error)
    texto = str(error)
    if nombre == _CONSTRAINT_ACTIVA or _CONSTRAINT_ACTIVA in texto:
        raise ValidationError(
            {"estado": "El empleado ya tiene una relación laboral activa en el grupo."}
        ) from error
    if nombre == _CONSTRAINT_SOLAPADA or _CONSTRAINT_SOLAPADA in texto:
        raise ValidationError(
            {"fecha_ingreso": "La vigencia se superpone con otra relación del empleado."}
        ) from error
    if nombre == _CONSTRAINT_FECHAS or _CONSTRAINT_FECHAS in texto:
        raise ValidationError(
            {"fecha_egreso": "La fecha de egreso no puede ser anterior al ingreso."}
        ) from error
    if nombre == _CONSTRAINT_CATALOGOS or _CONSTRAINT_CATALOGOS in texto:
        raise ValidationError(
            {"sector": "Una relación activa requiere sector y puesto."}
        ) from error
    if nombre == _CONSTRAINT_ESTADO_BAJA or _CONSTRAINT_ESTADO_BAJA in texto:
        raise ValidationError(
            {
                "estado": (
                    "Una relación activa no puede tener datos de baja y una finalizada "
                    "requiere fecha y motivo de egreso."
                )
            }
        ) from error
    raise error


def _traducir_integridad_documento(error: IntegrityError) -> None:
    nombre = _nombre_constraint(error)
    texto = str(error)
    if nombre == _CONSTRAINT_DOCUMENTO_UNICO or _CONSTRAINT_DOCUMENTO_UNICO in texto:
        raise ValidationError(
            {
                "tipo_documento": (
                    "Esta relación laboral ya tiene un documento de este tipo. "
                    "Para renovarlo, editá el existente."
                )
            }
        ) from error
    if nombre == _CONSTRAINT_DOCUMENTO_RELACION or _CONSTRAINT_DOCUMENTO_RELACION in texto:
        raise ValidationError(
            {"relacion_laboral": "El documento requiere una relación laboral activa."}
        ) from error
    raise error


def _traducir_integridad_empleado(error: IntegrityError) -> None:
    """Convierte la carrera validate→UNIQUE en un 400 de contrato estable."""

    nombre = _nombre_constraint(error)
    texto = str(error)
    for constraint, (campo, mensaje) in _CONSTRAINT_IDENTIFICADORES.items():
        if nombre == constraint or constraint in texto:
            raise ValidationError({campo: mensaje}) from error
    raise error


def _fecha_de_relacion(campo: str, valor):
    return RelacionLaboral._meta.get_field(campo).to_python(valor)


def _vencimiento_contrato_valido(*, fecha_ingreso, fecha_vencimiento):
    if fecha_vencimiento in (None, ""):
        return None
    vencimiento = _fecha_de_relacion(
        "fecha_vencimiento_contrato",
        fecha_vencimiento,
    )
    if vencimiento < fecha_ingreso:
        raise ValidationError(
            {
                "fecha_vencimiento_contrato": (
                    "El vencimiento del contrato no puede ser anterior al ingreso."
                )
            }
        )
    return vencimiento


def _borrar_binario_nuevo(archivo) -> None:
    """Compensa el storage, que no participa del rollback de la base."""
    if (
        not archivo
        or not getattr(archivo, "name", "")
        or not getattr(archivo, "_committed", False)
    ):
        return
    try:
        archivo.delete(save=False)
    except Exception:
        # Nunca se oculta el error de negocio/DB original por un fallo secundario de storage.
        pass


def _error_supervisor(supervisor) -> str | None:
    if supervisor is None:
        return None
    if not supervisor.is_active:
        return "No se puede asignar un usuario inactivo como supervisor."
    if supervisor.groups.filter(name=roles.SERVICIO).exists():
        return "Una identidad de Servicio no puede supervisar empleados."
    if not supervisor.groups.filter(name=roles.SUPERVISOR).exists():
        return "El usuario asignado debe pertenecer al rol Supervisor."
    return None


def _validar_catalogos_relacion(datos: dict) -> None:
    empresa = datos.get("empresa")
    sector = datos.get("sector")
    puesto = datos.get("puesto")
    supervisor = datos.get("supervisor")
    errores = {}

    if empresa is None:
        errores["empresa"] = "La empresa es obligatoria."
    elif not Empresa.objects.select_for_update().filter(
        pk=empresa.pk, activa=True
    ).exists():
        errores["empresa"] = "La empresa seleccionada está inactiva."

    if sector is None:
        errores["sector"] = "El sector es obligatorio."
    elif not Sector.objects.select_for_update().filter(
        pk=sector.pk, activo=True
    ).exists():
        errores["sector"] = "El sector seleccionado está inactivo."

    if puesto is None:
        errores["puesto"] = "El puesto es obligatorio."
    elif not Puesto.objects.select_for_update().filter(
        pk=puesto.pk, activo=True
    ).exists():
        errores["puesto"] = "El puesto seleccionado está inactivo."
    elif sector is not None and not Puesto.objects.filter(
        pk=puesto.pk, sector=sector
    ).exists():
        errores["puesto"] = "El puesto seleccionado no pertenece al sector indicado."

    if supervisor is not None:
        # Mutex compartido con cambios de estado/roles de Usuario. Se relee bajo lock:
        # el objeto que validó el serializer puede haber cambiado antes de este service.
        supervisor = Usuario.objects.select_for_update().get(pk=supervisor.pk)
        datos["supervisor"] = supervisor
    error_supervisor = _error_supervisor(supervisor)
    if error_supervisor:
        errores["supervisor"] = error_supervisor

    if errores:
        raise ValidationError(errores)


def _relaciones_solapadas(*, empleado: Empleado, desde, hasta, excluir_id=None):
    qs = RelacionLaboral.objects.filter(
        Q(fecha_egreso__isnull=True) | Q(fecha_egreso__gte=desde),
        empleado=empleado,
    )
    if hasta is not None:
        qs = qs.filter(fecha_ingreso__lte=hasta)
    if excluir_id is not None:
        qs = qs.exclude(pk=excluir_id)
    return qs


@transaction.atomic
def crear_empleado(*, actor, datos_empleado: dict, datos_relacion: dict) -> Empleado:
    """Alta de empleado + su relación laboral ACTIVA en la misma transacción (spec §1.1)."""
    try:
        with transaction.atomic():
            empleado = Empleado.objects.create(
                creado_por=actor,
                legajo=_asignar_legajo(),
                **datos_empleado,
            )
    except IntegrityError as error:
        _traducir_integridad_empleado(error)
    registrar_evento(actor=actor, accion=Accion.EMPLEADO_CREADO, objeto=empleado)
    # La relación asienta su propio evento: son dos hechos, y la baja de mañana toca uno solo.
    crear_relacion_laboral(actor=actor, empleado=empleado, **datos_relacion)
    return empleado


@transaction.atomic
def actualizar_empleado(*, actor, empleado: Empleado, datos_empleado: dict) -> Empleado:
    empleado = Empleado.objects.select_for_update().get(pk=empleado.pk)
    antes = tomar_foto(empleado)
    for campo, valor in datos_empleado.items():
        setattr(empleado, campo, valor)
    try:
        with transaction.atomic():
            empleado.save()
    except IntegrityError as error:
        _traducir_integridad_empleado(error)
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
    # Todas las operaciones sobre la vida laboral toman primero la persona. Así se
    # serializan alta/reingreso/baja y se evita el deadlock de bloquear en distinto orden.
    empleado = Empleado.objects.select_for_update().get(pk=empleado.pk)
    _validar_catalogos_relacion(datos)

    if not datos.get("fecha_ingreso"):
        raise ValidationError({"fecha_ingreso": "La fecha de ingreso es obligatoria."})
    desde = _fecha_de_relacion("fecha_ingreso", datos.get("fecha_ingreso"))
    hasta = _fecha_de_relacion("fecha_egreso", datos.get("fecha_egreso"))
    datos["fecha_ingreso"] = desde
    if "fecha_vencimiento_contrato" in datos:
        datos["fecha_vencimiento_contrato"] = _vencimiento_contrato_valido(
            fecha_ingreso=desde,
            fecha_vencimiento=datos["fecha_vencimiento_contrato"],
        )
    if "fecha_egreso" in datos:
        datos["fecha_egreso"] = hasta

    motivo_egreso = str(datos.get("motivo_egreso", "") or "").strip()
    if "motivo_egreso" in datos:
        datos["motivo_egreso"] = motivo_egreso
    if motivo_egreso:
        motivo_egreso = _motivo_egreso_valido(motivo_egreso)
        datos["motivo_egreso"] = motivo_egreso
    if estado == EstadoRelacion.ACTIVA and (hasta is not None or motivo_egreso):
        raise ValidationError(
            {"estado": "Una relación activa no puede tener fecha ni motivo de egreso."}
        )
    if estado == EstadoRelacion.FINALIZADA and (hasta is None or not motivo_egreso):
        raise ValidationError(
            {
                "estado": (
                    "Una relación finalizada requiere fecha y motivo de egreso."
                )
            }
        )
    if hasta is not None and hasta < desde:
        raise ValidationError(
            {"fecha_egreso": "La fecha de egreso no puede ser anterior al ingreso."}
        )
    if estado == EstadoRelacion.ACTIVA and RelacionLaboral.objects.filter(
        empleado=empleado, estado=EstadoRelacion.ACTIVA
    ).exists():
        raise ValidationError(
            {"estado": "El empleado ya tiene una relación laboral activa en el grupo."}
        )
    if _relaciones_solapadas(empleado=empleado, desde=desde, hasta=hasta).exists():
        raise ValidationError(
            {"fecha_ingreso": "La vigencia se superpone con otra relación del empleado."}
        )

    try:
        # Savepoint interno: permite traducir el IntegrityError sin dejar rota la
        # transacción exterior que también contiene el evento de auditoría.
        with transaction.atomic():
            relacion = RelacionLaboral.objects.create(
                creado_por=actor, empleado=empleado, estado=estado, **datos
            )
    except IntegrityError as error:
        _traducir_integridad_relacion(error)

    registrar_evento(actor=actor, accion=Accion.RELACION_CREADA, objeto=relacion)
    return relacion


@transaction.atomic
def asignar_supervisor_relacion(
    *, actor, relacion: RelacionLaboral, supervisor
) -> RelacionLaboral:
    """Asigna o quita responsable sin reescribir el resto del vínculo laboral."""
    # Conserva el mismo orden de locks que alta/baja: primero persona, luego relación.
    Empleado.objects.select_for_update().get(pk=relacion.empleado_id)
    relacion = (
        RelacionLaboral.objects.select_for_update(of=("self",))
        .select_related("empleado", "empresa", "sector", "puesto", "supervisor")
        .get(pk=relacion.pk)
    )
    if relacion.estado != EstadoRelacion.ACTIVA:
        raise ValidationError(
            {"estado": "Solo se puede cambiar el supervisor de una relación activa."}
        )
    if supervisor is not None:
        supervisor = Usuario.objects.select_for_update().get(pk=supervisor.pk)
    error_supervisor = _error_supervisor(supervisor)
    if error_supervisor:
        raise ValidationError({"supervisor": error_supervisor})
    if relacion.supervisor_id == getattr(supervisor, "pk", None):
        return relacion

    antes = tomar_foto(relacion, campos=("supervisor",))
    relacion.supervisor = supervisor
    relacion.save(update_fields=["supervisor", "actualizado_en"])
    registrar_evento(
        actor=actor,
        accion=Accion.RELACION_SUPERVISOR_CAMBIADO,
        objeto=relacion,
        antes=antes,
        campos=("supervisor",),
        solo_si_cambia=True,
    )
    return relacion


@transaction.atomic
def actualizar_relacion_laboral(
    *, actor, relacion: RelacionLaboral, datos: dict
) -> RelacionLaboral:
    """Actualiza la asignación actual y deja el antes/después en la bitácora append-only.

    Empresa, ingreso, egreso, estado y supervisor tienen flujos propios y no se aceptan
    aquí. Así una promoción no se disfraza de baja/reingreso ni reescribe la vida laboral.
    """
    permitidos = {
        "sector",
        "puesto",
        "jornada_legal",
        "tipo_contrato",
        "fecha_vencimiento_contrato",
    }
    desconocidos = set(datos) - permitidos
    if desconocidos:
        raise ValidationError(
            {"campos": f"No se pueden editar en este flujo: {sorted(desconocidos)}."}
        )
    if not datos:
        return RelacionLaboral.objects.get(pk=relacion.pk)

    Empleado.objects.select_for_update().get(pk=relacion.empleado_id)
    relacion = RelacionLaboral.objects.select_for_update().get(pk=relacion.pk)
    if relacion.estado != EstadoRelacion.ACTIVA:
        raise ValidationError(
            {"estado": "Solo se puede modificar una relación laboral activa."}
        )

    resultado = {
        "empresa": relacion.empresa,
        "sector": datos.get("sector", relacion.sector),
        "puesto": datos.get("puesto", relacion.puesto),
        "supervisor": relacion.supervisor,
    }
    sector_resultante = resultado["sector"]
    if (
        sector_resultante is not None
        and relacion.sector_id != sector_resultante.pk
        and relacion.procesos_checklist.exists()
    ):
        raise ValidationError(
            {
                "sector": (
                    "No se puede cambiar el sector porque la relación ya tiene un "
                    "onboarding u offboarding iniciado. El checklist conserva el sector "
                    "del ingreso; una transferencia requiere un flujo específico."
                )
            }
        )
    _validar_catalogos_relacion(resultado)

    if "fecha_vencimiento_contrato" in datos:
        datos["fecha_vencimiento_contrato"] = _vencimiento_contrato_valido(
            fecha_ingreso=relacion.fecha_ingreso,
            fecha_vencimiento=datos["fecha_vencimiento_contrato"],
        )

    campos = tuple(sorted(permitidos))
    antes = tomar_foto(relacion, campos=campos)
    for campo, valor in datos.items():
        setattr(relacion, campo, valor)
    try:
        with transaction.atomic():
            relacion.save(
                update_fields=[*datos.keys(), "actualizado_en"]
            )
    except IntegrityError as error:
        _traducir_integridad_relacion(error)
    registrar_evento(
        actor=actor,
        accion=Accion.RELACION_ACTUALIZADA,
        objeto=relacion,
        antes=antes,
        campos=campos,
        solo_si_cambia=True,
    )
    return relacion


@transaction.atomic
def actualizar_ficha_completa(
    *,
    actor,
    empleado: Empleado,
    datos_empleado: dict,
    relacion: RelacionLaboral | None,
    datos_relacion: dict,
) -> Empleado:
    """Edición de ficha sin estados parciales entre persona y asignación."""
    if datos_empleado:
        empleado = actualizar_empleado(
            actor=actor,
            empleado=empleado,
            datos_empleado=datos_empleado,
        )
    if datos_relacion:
        if relacion is None:
            raise ValidationError(
                {"relacion": "El empleado no tiene una relación laboral activa."}
            )
        actualizar_relacion_laboral(
            actor=actor,
            relacion=relacion,
            datos=datos_relacion,
        )
    return empleado


@transaction.atomic
def finalizar_relacion(
    *, actor, relacion: RelacionLaboral, fecha_egreso, motivo_egreso: str
) -> RelacionLaboral:
    """R10: baja lógica. Finaliza la relación con fecha y motivo; no borra nada."""
    Empleado.objects.select_for_update().get(pk=relacion.empleado_id)
    relacion = (
        RelacionLaboral.objects.select_for_update(of=("self",))
        .select_related("empleado", "empresa", "sector", "puesto", "supervisor")
        .get(pk=relacion.pk)
    )
    if relacion.estado != EstadoRelacion.ACTIVA:
        raise ValidationError({"estado": "La relación laboral ya está finalizada."})
    fecha_egreso = _fecha_de_relacion("fecha_egreso", fecha_egreso)
    motivo_egreso = _motivo_egreso_valido(motivo_egreso)
    if relacion.fecha_ingreso and fecha_egreso < relacion.fecha_ingreso:
        raise ValidationError(
            {"fecha_egreso": "La fecha de egreso no puede ser anterior al ingreso."}
        )
    from apps.novedades.models import OCUPAN_PERIODO, Novedad

    novedad_fuera_de_vigencia = (
        Novedad.objects.select_for_update()
        .filter(
            relacion_laboral=relacion,
            estado__in=OCUPAN_PERIODO,
        )
        .filter(
            Q(fecha_desde__gt=fecha_egreso)
            | Q(fecha_hasta__isnull=True)
            | Q(fecha_hasta__gt=fecha_egreso)
        )
        .order_by("fecha_desde", "id")
        .first()
    )
    if novedad_fuera_de_vigencia is not None:
        raise ValidationError(
            {
                "fecha_egreso": (
                    "La relación tiene una novedad vigente o posterior a esa fecha "
                    f"(id {novedad_fuera_de_vigencia.id}). Cerrala, anulala o corregí "
                    "su período antes de registrar el egreso."
                )
            }
        )
    antes = tomar_foto(relacion)
    relacion.estado = EstadoRelacion.FINALIZADA
    relacion.fecha_egreso = fecha_egreso
    relacion.motivo_egreso = motivo_egreso
    try:
        with transaction.atomic():
            relacion.save(
                update_fields=["estado", "fecha_egreso", "motivo_egreso", "actualizado_en"]
            )
    except IntegrityError as error:
        _traducir_integridad_relacion(error)
    # La baja es EL evento que se le va a pedir a esta bitácora en una disputa laboral.
    registrar_evento(
        actor=actor, accion=Accion.RELACION_FINALIZADA, objeto=relacion, antes=antes
    )
    return relacion


@transaction.atomic
def crear_documento(*, actor, empleado: Empleado, **datos) -> DocumentoEmpleado:
    """Crea el documento dentro de la relación activa actual.

    La FK no se acepta del cliente: derivarla bajo el mismo lock que alta/baja evita que
    una finalización concurrente deje el documento asociado a otra etapa laboral.
    """
    if "relacion_laboral" in datos:
        raise ValidationError(
            {"relacion_laboral": "La relación laboral se determina automáticamente."}
        )
    empleado = Empleado.objects.select_for_update().get(pk=empleado.pk)
    relacion = (
        RelacionLaboral.objects.select_for_update()
        .filter(empleado=empleado, estado=EstadoRelacion.ACTIVA)
        .first()
    )
    if relacion is None:
        raise ValidationError(
            {
                "relacion_laboral": (
                    "No se puede cargar el documento porque el empleado no tiene "
                    "una relación laboral activa."
                )
            }
        )

    tipo_documento = datos.get("tipo_documento")
    tipo_documento = (
        TipoDocumento.objects.select_for_update()
        .filter(
            pk=getattr(tipo_documento, "pk", None),
            activo=True,
        )
        .first()
    )
    if tipo_documento is None:
        raise ValidationError(
            {"tipo_documento": "El tipo de documento está inactivo o no existe."}
        )
    datos["tipo_documento"] = tipo_documento
    if DocumentoEmpleado.objects.filter(
        relacion_laboral=relacion, tipo_documento=tipo_documento
    ).exists():
        raise ValidationError(
            {
                "tipo_documento": (
                    "Esta relación laboral ya tiene un documento de este tipo. "
                    "Para renovarlo, editá el existente."
                )
            }
        )
    documento = DocumentoEmpleado(
        creado_por=actor,
        empleado=empleado,
        relacion_laboral=relacion,
        **datos,
    )
    try:
        try:
            with transaction.atomic():
                documento.save()
        except IntegrityError as error:
            _traducir_integridad_documento(error)
        registrar_evento(actor=actor, accion=Accion.DOCUMENTO_CREADO, objeto=documento)
    except Exception:
        _borrar_binario_nuevo(documento.archivo)
        raise
    return documento




@transaction.atomic
def actualizar_documento(*, actor, documento: DocumentoEmpleado, **datos) -> DocumentoEmpleado:
    """Corrección y renovación de un documento (número, vencimiento, archivo, observaciones).

    Sin esto, el UNIQUE (relación, tipo_documento) convertiría cualquier documento cargado
    en un callejón sin salida: no se podría corregir un vencimiento mal tipeado.

    Renovar (apto médico nuevo) es mover `fecha_vencimiento` y reemplazar el archivo: no se
    conserva el ARCHIVO anterior. Es deliberado y acordado — un carnet o un CNRT viejo es
    basura, no historia. Lo que sí queda desde RP8 es el rastro del cambio en la bitácora
    (qué vencimiento tenía antes, quién lo movió y cuándo), que es lo que se discute cuando
    alguien pregunta por qué figuraba vigente. El respaldo de un hecho puntual (el
    certificado de una licencia, los estudios de un accidente) no vive acá: pertenece a su
    novedad, que lo conserva sola porque las novedades no se borran nunca.

    El tipo no se edita: cambiar el tipo es otro documento (borrá este y cargá el correcto).
    """
    Empleado.objects.select_for_update().get(pk=documento.empleado_id)
    documento = (
        DocumentoEmpleado.objects.select_for_update(of=("self",))
        .select_related("relacion_laboral", "empleado", "tipo_documento")
        .get(pk=documento.pk)
    )
    if (
        documento.relacion_laboral_id is None
        or documento.relacion_laboral.estado != EstadoRelacion.ACTIVA
    ):
        raise ValidationError(
            {"relacion_laboral": "Los documentos de una relación histórica están congelados."}
        )

    # La referencia al archivo viejo se guarda ANTES de pisar el campo: después de asignar
    # el nuevo, el viejo queda sin quien lo nombre y el binario huérfano en disco.
    archivo_viejo = None
    if "archivo" in datos and documento.archivo and datos["archivo"] != documento.archivo:
        archivo_viejo = documento.archivo
    antes = tomar_foto(documento)
    for campo, valor in datos.items():
        setattr(documento, campo, valor)
    try:
        documento.save()
        registrar_evento(
            actor=actor,
            accion=Accion.DOCUMENTO_ACTUALIZADO,
            objeto=documento,
            antes=antes,
            solo_si_cambia=True,
        )
    except Exception:
        if "archivo" in datos and documento.archivo != archivo_viejo:
            _borrar_binario_nuevo(documento.archivo)
        raise
    borrar_archivo_al_confirmar(archivo_viejo)
    return documento


@transaction.atomic
def guardar_foto_empleado(*, actor, empleado: Empleado, foto) -> Empleado:
    """Setea (o reemplaza) la foto de perfil. La anterior se borra al confirmar.

    Reemplazar deja el binario viejo sin quien lo nombre; se libera con la misma red que los
    documentos (`borrar_archivo_al_confirmar`), después del commit y no antes.
    """
    empleado = Empleado.objects.select_for_update().get(pk=empleado.pk)
    foto_vieja = empleado.foto if empleado.foto else None
    antes = tomar_foto(empleado, campos=("foto",))
    empleado.foto = foto
    try:
        empleado.save(update_fields=["foto", "actualizado_en"])
        # `campos` acota el diff a la foto: el resto de la ficha no cambió y sería ruido.
        registrar_evento(
            actor=actor,
            accion=Accion.EMPLEADO_FOTO_CAMBIADA,
            objeto=empleado,
            antes=antes,
            campos=("foto",),
        )
    except Exception:
        if empleado.foto != foto_vieja:
            _borrar_binario_nuevo(empleado.foto)
        raise
    if foto_vieja and foto_vieja != empleado.foto:
        borrar_archivo_al_confirmar(foto_vieja)
    return empleado


@transaction.atomic
def eliminar_foto_empleado(*, actor, empleado: Empleado) -> Empleado:
    """Quita la foto de perfil y borra el binario al confirmar."""
    empleado = Empleado.objects.select_for_update().get(pk=empleado.pk)
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
    Empleado.objects.select_for_update().get(pk=documento.empleado_id)
    documento = (
        DocumentoEmpleado.objects.select_for_update(of=("self",))
        .select_related("relacion_laboral")
        .get(pk=documento.pk)
    )
    if (
        documento.relacion_laboral_id is None
        or documento.relacion_laboral.estado != EstadoRelacion.ACTIVA
    ):
        raise ValidationError(
            {"relacion_laboral": "Los documentos de una relación histórica están congelados."}
        )
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
