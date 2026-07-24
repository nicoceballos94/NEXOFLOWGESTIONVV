"""Invariantes de relaciones laborales que deben sostenerse fuera de la API."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, close_old_connections, transaction
from rest_framework.exceptions import ValidationError

from apps.empleados import services
from apps.empleados.models import (
    DocumentoEmpleado,
    Empleado,
    EstadoRelacion,
    RelacionLaboral,
    TipoDocumento,
)
from apps.organizacion.models import Empresa, Puesto, Sector

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def catalogos():
    sector = Sector.objects.create(nombre="Operaciones")
    puesto = Puesto.objects.create(nombre="Chofer", sector=sector)
    empresa = Empresa.objects.create(nombre="Vial Victoria")
    return empresa, sector, puesto


@pytest.fixture
def empleado():
    return Empleado.objects.create(
        legajo="0100",
        dni="30111222",
        nombre="Juan",
        apellido="Pérez",
    )


def _crear_relacion(empleado, catalogos, **cambios):
    empresa, sector, puesto = catalogos
    datos = {
        "empresa": empresa,
        "sector": sector,
        "puesto": puesto,
        "fecha_ingreso": "2024-01-01",
    }
    datos.update(cambios)
    return services.crear_relacion_laboral(actor=None, empleado=empleado, **datos)


def test_modelo_rechaza_nacimiento_futuro():
    with pytest.raises(DjangoValidationError, match="futuro"):
        Empleado.objects.create(
            legajo="FUT-1",
            dni="30999111",
            nombre="Fecha",
            apellido="Imposible",
            fecha_nacimiento="2099-01-01",
        )


def test_service_traduce_carrera_de_dni_unico_a_validacion(
    empleado,
    catalogos,
):
    empresa, sector, puesto = catalogos

    with pytest.raises(ValidationError) as error:
        services.crear_empleado(
            actor=None,
            datos_empleado={
                "dni": empleado.dni,
                "nombre": "Duplicado",
                "apellido": "Concurrente",
            },
            datos_relacion={
                "empresa": empresa,
                "sector": sector,
                "puesto": puesto,
                "fecha_ingreso": "2025-01-01",
            },
        )

    assert "dni" in error.value.detail


def test_service_traduce_carrera_de_cuil_unico_en_edicion():
    primero = Empleado.objects.create(
        legajo="CUIL-1",
        dni="30999112",
        cuil="20309991122",
        nombre="Primero",
        apellido="CUIL",
    )
    segundo = Empleado.objects.create(
        legajo="CUIL-2",
        dni="30999113",
        nombre="Segundo",
        apellido="CUIL",
    )

    with pytest.raises(ValidationError) as error:
        services.actualizar_empleado(
            actor=None,
            empleado=segundo,
            datos_empleado={"cuil": primero.cuil},
        )

    assert "cuil" in error.value.detail


@pytest.mark.parametrize("campo", ["empresa", "sector", "puesto"])
def test_el_service_rechaza_catalogos_inactivos(empleado, catalogos, campo):
    empresa, sector, puesto = catalogos
    if campo == "empresa":
        empresa.activa = False
        empresa.save(update_fields=["activa"])
    elif campo == "sector":
        sector.activo = False
        sector.save(update_fields=["activo"])
    else:
        puesto.activo = False
        puesto.save(update_fields=["activo"])

    with pytest.raises(ValidationError) as error:
        _crear_relacion(empleado, catalogos)

    assert campo in error.value.detail
    assert not RelacionLaboral.objects.filter(empleado=empleado).exists()


def test_el_service_rechaza_puesto_de_otro_sector(empleado, catalogos):
    otro_sector = Sector.objects.create(nombre="Taller")
    otro_puesto = Puesto.objects.create(nombre="Mecánico", sector=otro_sector)

    with pytest.raises(ValidationError) as error:
        _crear_relacion(empleado, catalogos, puesto=otro_puesto)

    assert "puesto" in error.value.detail


@pytest.mark.parametrize("caso", ["sin_rol", "inactivo", "servicio"])
def test_el_service_no_permite_supervisores_no_asignables(
    empleado, catalogos, crear_usuario, caso
):
    from common import roles

    relacion = _crear_relacion(empleado, catalogos)
    if caso == "sin_rol":
        candidato = crear_usuario(username="sin-rol-supervisor", rol=roles.RRHH)
    elif caso == "servicio":
        candidato = crear_usuario(
            username="identidad-servicio",
            rol=roles.SERVICIO,
        )
    else:
        candidato = crear_usuario(
            username=f"supervisor-{caso}",
            rol=roles.SUPERVISOR,
            is_active=caso != "inactivo",
        )

    with pytest.raises(ValidationError) as error:
        services.asignar_supervisor_relacion(
            actor=None,
            relacion=relacion,
            supervisor=candidato,
        )

    assert "supervisor" in error.value.detail
    relacion.refresh_from_db()
    assert relacion.supervisor_id is None


def test_la_base_exige_sector_y_puesto_en_una_relacion_activa(empleado, catalogos):
    empresa, _, _ = catalogos

    with pytest.raises(IntegrityError), transaction.atomic():
        RelacionLaboral.objects.create(
            empleado=empleado,
            empresa=empresa,
            fecha_ingreso=date(2024, 1, 1),
            estado=EstadoRelacion.ACTIVA,
        )


def test_la_base_permite_una_sola_relacion_activa_total(empleado, catalogos):
    empresa, sector, puesto = catalogos
    _crear_relacion(empleado, catalogos)
    otra_empresa = Empresa.objects.create(nombre="Otra empresa")

    with pytest.raises(IntegrityError), transaction.atomic():
        RelacionLaboral.objects.create(
            empleado=empleado,
            empresa=otra_empresa,
            sector=sector,
            puesto=puesto,
            fecha_ingreso=date(2025, 1, 1),
            estado=EstadoRelacion.ACTIVA,
        )

    assert RelacionLaboral.objects.filter(
        empleado=empleado, estado=EstadoRelacion.ACTIVA
    ).count() == 1


def test_la_base_exige_coherencia_entre_estado_y_datos_de_baja(
    empleado, catalogos
):
    empresa, sector, puesto = catalogos
    with pytest.raises(IntegrityError), transaction.atomic():
        RelacionLaboral.objects.create(
            empleado=empleado,
            empresa=empresa,
            sector=sector,
            puesto=puesto,
            fecha_ingreso=date(2024, 1, 1),
            fecha_egreso=date(2024, 12, 31),
            motivo_egreso="RENUNCIA",
            estado=EstadoRelacion.ACTIVA,
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        RelacionLaboral.objects.create(
            empleado=empleado,
            empresa=empresa,
            sector=sector,
            puesto=puesto,
            fecha_ingreso=date(2024, 1, 1),
            fecha_egreso=date(2024, 12, 31),
            motivo_egreso="",
            estado=EstadoRelacion.FINALIZADA,
        )


def test_los_periodos_son_inclusivos_y_no_pueden_solaparse(empleado, catalogos):
    primera = _crear_relacion(empleado, catalogos)
    services.finalizar_relacion(
        actor=None,
        relacion=primera,
        fecha_egreso="2024-12-31",
        motivo_egreso="RENUNCIA",
    )

    with pytest.raises(ValidationError) as error:
        _crear_relacion(
            empleado,
            catalogos,
            fecha_ingreso="2024-12-31",
        )
    assert "fecha_ingreso" in error.value.detail

    segunda = _crear_relacion(
        empleado,
        catalogos,
        fecha_ingreso="2025-01-01",
    )
    assert segunda.estado == EstadoRelacion.ACTIVA


def test_la_exclusion_de_base_frena_un_solapamiento_historico(empleado, catalogos):
    empresa, sector, puesto = catalogos
    RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=empresa,
        sector=sector,
        puesto=puesto,
        fecha_ingreso=date(2020, 1, 1),
        fecha_egreso=date(2020, 12, 31),
        motivo_egreso="RENUNCIA",
        estado=EstadoRelacion.FINALIZADA,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        RelacionLaboral.objects.create(
            empleado=empleado,
            empresa=empresa,
            sector=sector,
            puesto=puesto,
            fecha_ingreso=date(2020, 12, 31),
            fecha_egreso=date(2021, 6, 1),
            motivo_egreso="RENUNCIA",
            estado=EstadoRelacion.FINALIZADA,
        )


def test_antiguedad_abierta_usa_la_fecha_local(monkeypatch, empleado, catalogos):
    relacion = _crear_relacion(empleado, catalogos, fecha_ingreso="2024-07-01")
    monkeypatch.setattr(
        "apps.empleados.models.timezone.localdate",
        lambda: date(2024, 7, 11),
    )

    assert relacion.antiguedad_en_dias == 10


def test_no_finaliza_si_una_novedad_quedaria_fuera_de_la_vigencia(
    empleado, catalogos
):
    from apps.novedades.models import Novedad, TipoNovedad

    relacion = _crear_relacion(empleado, catalogos)
    tipo = TipoNovedad.objects.create(codigo="LICENCIA", nombre="Licencia")
    novedad = Novedad.objects.create(
        empleado=empleado,
        relacion_laboral=relacion,
        tipo_novedad=tipo,
        fecha_desde=date(2025, 1, 10),
        fecha_hasta=date(2025, 1, 20),
    )

    with pytest.raises(ValidationError) as error:
        services.finalizar_relacion(
            actor=None,
            relacion=relacion,
            fecha_egreso="2024-12-31",
            motivo_egreso="RENUNCIA",
        )

    assert "fecha_egreso" in error.value.detail
    assert str(novedad.id) in str(error.value.detail)
    relacion.refresh_from_db()
    assert relacion.estado == EstadoRelacion.ACTIVA


def test_documento_debe_pertenecer_al_mismo_empleado(empleado, catalogos):
    relacion = _crear_relacion(empleado, catalogos)
    otro = Empleado.objects.create(
        legajo="0101",
        dni="30222333",
        nombre="Ana",
        apellido="Gómez",
    )
    tipo = TipoDocumento.objects.create(nombre="Apto médico")
    documento = DocumentoEmpleado(
        empleado=otro,
        relacion_laboral=relacion,
        tipo_documento=tipo,
    )

    with pytest.raises(DjangoValidationError) as error:
        documento.full_clean()

    assert "relacion_laboral" in error.value.message_dict


def test_la_base_exige_relacion_y_unicidad_documental_por_vinculo(
    empleado, catalogos
):
    relacion = _crear_relacion(empleado, catalogos)
    tipo = TipoDocumento.objects.create(nombre="Apto médico")

    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentoEmpleado.objects.create(
            empleado=empleado,
            tipo_documento=tipo,
        )

    DocumentoEmpleado.objects.create(
        empleado=empleado,
        relacion_laboral=relacion,
        tipo_documento=tipo,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        DocumentoEmpleado.objects.create(
            empleado=empleado,
            relacion_laboral=relacion,
            tipo_documento=tipo,
        )


def test_dos_altas_concurrentes_dejan_una_y_un_error_amigable(empleado, catalogos):
    barrera = Barrier(2)

    def alta_concurrente():
        close_old_connections()
        try:
            barrera.wait()
            return _crear_relacion(empleado, catalogos)
        except Exception as error:  # se inspecciona el tipo exacto abajo
            return error
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        resultados = list(ejecutor.map(lambda _: alta_concurrente(), range(2)))

    exitos = [resultado for resultado in resultados if isinstance(resultado, RelacionLaboral)]
    errores = [resultado for resultado in resultados if isinstance(resultado, ValidationError)]
    assert len(exitos) == 1, resultados
    assert len(errores) == 1, resultados
    assert "estado" in errores[0].detail
    assert RelacionLaboral.objects.filter(
        empleado=empleado, estado=EstadoRelacion.ACTIVA
    ).count() == 1


def test_dos_bajas_concurrentes_no_pisan_la_historia(empleado, catalogos):
    relacion = _crear_relacion(empleado, catalogos)
    barrera = Barrier(2)

    def baja_concurrente():
        close_old_connections()
        try:
            barrera.wait()
            return services.finalizar_relacion(
                actor=None,
                relacion=relacion,
                fecha_egreso="2024-12-31",
                motivo_egreso="RENUNCIA",
            )
        except Exception as error:  # se inspecciona el tipo exacto abajo
            return error
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        resultados = list(ejecutor.map(lambda _: baja_concurrente(), range(2)))

    exitos = [resultado for resultado in resultados if isinstance(resultado, RelacionLaboral)]
    errores = [resultado for resultado in resultados if isinstance(resultado, ValidationError)]
    assert len(exitos) == 1, resultados
    assert len(errores) == 1, resultados
    assert "estado" in errores[0].detail
    relacion.refresh_from_db()
    assert relacion.estado == EstadoRelacion.FINALIZADA
    assert relacion.fecha_egreso == date(2024, 12, 31)


def test_asignacion_y_desactivacion_concurrentes_no_dejan_supervisor_invalido(
    empleado,
    catalogos,
    crear_usuario,
):
    from apps.usuarios.models import Usuario
    from common import roles

    relacion = _crear_relacion(empleado, catalogos)
    supervisor = crear_usuario(
        username="supervisor-carrera",
        rol=roles.SUPERVISOR,
    )
    barrera = Barrier(2)

    def asignar():
        close_old_connections()
        try:
            barrera.wait()
            return services.asignar_supervisor_relacion(
                actor=None,
                relacion=RelacionLaboral.objects.get(pk=relacion.pk),
                supervisor=Usuario.objects.get(pk=supervisor.pk),
            )
        except Exception as error:
            return error
        finally:
            close_old_connections()

    def desactivar():
        close_old_connections()
        try:
            barrera.wait()
            usuario = Usuario.objects.get(pk=supervisor.pk)
            usuario.is_active = False
            usuario.save(update_fields=["is_active"])
            return usuario
        except Exception as error:
            return error
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        futuros = [ejecutor.submit(asignar), ejecutor.submit(desactivar)]
        resultados = [futuro.result() for futuro in futuros]

    inesperados = [
        resultado
        for resultado in resultados
        if isinstance(resultado, Exception)
        and not isinstance(resultado, (ValidationError, DjangoValidationError))
    ]
    assert inesperados == []
    relacion.refresh_from_db()
    supervisor.refresh_from_db()
    assert not (
        relacion.supervisor_id == supervisor.pk
        and not supervisor.is_active
    )
