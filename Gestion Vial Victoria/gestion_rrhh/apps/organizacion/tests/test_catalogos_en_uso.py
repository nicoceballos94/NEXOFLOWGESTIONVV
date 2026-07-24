from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.empleados.models import Empleado, RelacionLaboral
from apps.organizacion.models import Empresa, Puesto, Sector
from common import roles

pytestmark = pytest.mark.django_db


@pytest.fixture
def cliente_rrhh(crear_usuario):
    cliente = APIClient()
    cliente.force_authenticate(
        crear_usuario(username="rrhh_catalogos", rol=roles.RRHH)
    )
    return cliente


@pytest.fixture
def relacion_activa():
    empresa = Empresa.objects.create(nombre="VIAL VICTORIA")
    sector = Sector.objects.create(nombre="Choferes")
    puesto = Puesto.objects.create(nombre="Chofer junior", sector=sector)
    empleado = Empleado.objects.create(
        legajo="CAT-001",
        dni="40111222",
        nombre="Ana",
        apellido="Prueba",
    )
    relacion = RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=empresa,
        sector=sector,
        puesto=puesto,
        fecha_ingreso=date(2025, 1, 1),
    )
    return relacion


def test_no_desactiva_empresa_con_relacion_activa(
    cliente_rrhh, relacion_activa
):
    respuesta = cliente_rrhh.patch(
        f"/api/v1/empresas/{relacion_activa.empresa_id}/",
        {"activa": False},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "activa" in respuesta.data["campos"]


def test_no_desactiva_sector_con_relacion_activa(
    cliente_rrhh, relacion_activa
):
    respuesta = cliente_rrhh.patch(
        f"/api/v1/sectores/{relacion_activa.sector_id}/",
        {"activo": False},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "activo" in respuesta.data["campos"]


def test_no_desactiva_puesto_con_relacion_activa(
    cliente_rrhh, relacion_activa
):
    respuesta = cliente_rrhh.patch(
        f"/api/v1/puestos/{relacion_activa.puesto_id}/",
        {"activo": False},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "activo" in respuesta.data["campos"]


def test_puesto_usado_no_se_mueve_de_sector(
    cliente_rrhh, relacion_activa
):
    otro = Sector.objects.create(nombre="Taller")

    respuesta = cliente_rrhh.patch(
        f"/api/v1/puestos/{relacion_activa.puesto_id}/",
        {"sector": otro.id},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "sector" in respuesta.data["campos"]


def test_sector_sin_relaciones_exige_apagar_primero_sus_puestos(
    cliente_rrhh,
):
    sector = Sector.objects.create(nombre="Administración")
    puesto = Puesto.objects.create(nombre="Analista", sector=sector)

    bloqueado = cliente_rrhh.patch(
        f"/api/v1/sectores/{sector.id}/",
        {"activo": False},
        format="json",
    )
    assert bloqueado.status_code == 400

    assert (
        cliente_rrhh.patch(
            f"/api/v1/puestos/{puesto.id}/",
            {"activo": False},
            format="json",
        ).status_code
        == 200
    )
    assert (
        cliente_rrhh.patch(
            f"/api/v1/sectores/{sector.id}/",
            {"activo": False},
            format="json",
        ).status_code
        == 200
    )
