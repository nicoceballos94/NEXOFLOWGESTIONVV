from datetime import date

import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.empleados.models import Empleado, EstadoRelacion, RelacionLaboral
from apps.organizacion.models import Empresa, Puesto, Sector
from common import roles

pytestmark = pytest.mark.django_db


@pytest.fixture
def empleado_para_reingreso():
    sector = Sector.objects.create(nombre="Operaciones")
    puesto = Puesto.objects.create(nombre="Chofer", sector=sector)
    empresa = Empresa.objects.create(nombre="Vial Victoria")
    empleado = Empleado.objects.create(
        legajo="0042",
        dni="30111222",
        nombre="Juan",
        apellido="Pérez",
        direccion="Belgrano 742",
    )
    RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=empresa,
        sector=sector,
        puesto=puesto,
        fecha_ingreso=date(2024, 1, 1),
        fecha_egreso=date(2025, 1, 31),
        motivo_egreso="RENUNCIA",
        estado=EstadoRelacion.FINALIZADA,
    )
    return empleado


def _cliente(usuario):
    cliente = APIClient()
    cliente.force_authenticate(usuario)
    return cliente


@pytest.mark.parametrize("dni_formateado", ["30.111.222", "30-111-222"])
def test_rrhh_busca_dni_completo_normalizado_y_audita_la_ficha(
    cliente_rrhh, empleado_para_reingreso, dni_formateado
):
    resp = cliente_rrhh.get(
        "/api/v1/empleados/por-dni/",
        {"dni": dni_formateado},
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["id"] == empleado_para_reingreso.id
    assert resp.data["dni"] == "30111222"
    assert resp.data["direccion"] == "Belgrano 742"
    assert resp.data["activo"] is False
    assert resp.data["relaciones"][0]["estado"] == EstadoRelacion.FINALIZADA
    evento = RegistroAuditoria.objects.get(
        accion=Accion.EMPLEADO_CONSULTADO,
        objeto_id=empleado_para_reingreso.id,
    )
    assert evento.empleado_id == empleado_para_reingreso.id
    assert evento.usuario_nombre == "rrhh"
    assert evento.valores_antes == {}
    assert evento.valores_despues == {}


def test_admin_tambien_puede_buscar_por_dni(
    crear_usuario, empleado_para_reingreso
):
    admin = crear_usuario(username="admin-dni", rol=roles.ADMIN)

    resp = _cliente(admin).get(
        "/api/v1/empleados/por-dni/",
        {"dni": empleado_para_reingreso.dni},
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["id"] == empleado_para_reingreso.id


@pytest.mark.parametrize("rol", [roles.SUPERVISOR, roles.EMPLEADO, roles.SERVICIO])
def test_busqueda_por_dni_niega_roles_sin_acceso(
    crear_usuario, empleado_para_reingreso, rol
):
    usuario = crear_usuario(username=f"sin-acceso-{rol.lower()}", rol=rol)

    resp = _cliente(usuario).get(
        "/api/v1/empleados/por-dni/",
        {"dni": empleado_para_reingreso.dni},
    )

    assert resp.status_code == 403
    assert not RegistroAuditoria.objects.filter(
        accion=Accion.EMPLEADO_CONSULTADO
    ).exists()


def test_identidad_servicio_mezclada_con_rrhh_tambien_se_niega(
    crear_usuario, empleado_para_reingreso
):
    usuario = crear_usuario(username="robot-rrhh", rol=roles.RRHH)
    servicio = Group.objects.get_or_create(name=roles.SERVICIO)[0]
    usuario.groups.through.objects.create(usuario=usuario, group=servicio)

    resp = _cliente(usuario).get(
        "/api/v1/empleados/por-dni/",
        {"dni": empleado_para_reingreso.dni},
    )

    assert resp.status_code == 403


@pytest.mark.parametrize(
    "parametros,estado",
    [
        ({}, 400),
        ({"dni": ""}, 400),
        ({"dni": "3011"}, 400),
        ({"dni": "30%111"}, 400),
        ({"dni": "99999999"}, 404),
    ],
)
def test_busqueda_por_dni_rechaza_entrada_incompleta_o_inexistente(
    cliente_rrhh, empleado_para_reingreso, parametros, estado
):
    resp = cliente_rrhh.get("/api/v1/empleados/por-dni/", parametros)

    assert resp.status_code == estado
    assert not RegistroAuditoria.objects.filter(
        accion=Accion.EMPLEADO_CONSULTADO
    ).exists()


def test_un_prefijo_valido_no_hace_busqueda_parcial(
    cliente_rrhh, empleado_para_reingreso
):
    resp = cliente_rrhh.get(
        "/api/v1/empleados/por-dni/",
        {"dni": "301112"},
    )

    assert resp.status_code == 404
    assert not RegistroAuditoria.objects.filter(
        accion=Accion.EMPLEADO_CONSULTADO
    ).exists()


def test_dos_parametros_dni_se_rechazan_por_ambiguos(
    cliente_rrhh, empleado_para_reingreso
):
    resp = cliente_rrhh.get(
        "/api/v1/empleados/por-dni/?dni=30111222&dni=301112",
    )

    assert resp.status_code == 400
