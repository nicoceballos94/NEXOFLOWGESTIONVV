from datetime import date

import pytest

from apps.empleados.models import Empleado, RelacionLaboral
from apps.novedades.models import Novedad, TipoNovedad
from apps.organizacion.models import Empresa, Puesto, Sector

pytestmark = pytest.mark.django_db


def _empleado_activo():
    empresa = Empresa.objects.create(nombre="Vial Victoria")
    sector = Sector.objects.create(nombre="Operaciones")
    puesto = Puesto.objects.create(nombre="Chofer", sector=sector)
    empleado = Empleado.objects.create(
        legajo="0001",
        dni="30111222",
        nombre="Juan",
        apellido="Pérez",
    )
    RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=empresa,
        sector=sector,
        puesto=puesto,
        fecha_ingreso=date(2024, 1, 1),
    )
    return empleado


def test_codigo_se_normaliza_y_semantica_usada_queda_inmutable(cliente_rrhh):
    alta_tipo = cliente_rrhh.post(
        "/api/v1/tipos-novedad/",
        {
            "codigo": "licencia-medica",
            "nombre": "Licencia médica",
            "justifica_ausencia": True,
            "ocupa_periodo": True,
            "requiere_certificado": True,
            "admite_prorroga": True,
            "requiere_cantidad_horas": False,
        },
        format="json",
    )
    assert alta_tipo.status_code == 201, alta_tipo.data
    assert alta_tipo.data["codigo"] == "LICENCIA_MEDICA"
    empleado = _empleado_activo()
    novedad = cliente_rrhh.post(
        "/api/v1/novedades/",
        {
            "empleado": empleado.pk,
            "tipo_novedad": alta_tipo.data["id"],
            "fecha_desde": "2025-03-01",
            "fecha_hasta": "2025-03-05",
        },
        format="json",
    )
    assert novedad.status_code == 201, novedad.data

    cambio_semantico = cliente_rrhh.patch(
        f"/api/v1/tipos-novedad/{alta_tipo.data['id']}/",
        {
            "codigo": "HORAS_EXTRA",
            "ocupa_periodo": False,
            "requiere_cantidad_horas": True,
        },
        format="json",
    )

    assert cambio_semantico.status_code == 400, cambio_semantico.data
    tipo = TipoNovedad.objects.get(pk=alta_tipo.data["id"])
    assert tipo.codigo == "LICENCIA_MEDICA"
    assert tipo.ocupa_periodo is True
    assert tipo.requiere_cantidad_horas is False
    assert Novedad.objects.get().ocupa_periodo is True

    cambio_editorial = cliente_rrhh.patch(
        f"/api/v1/tipos-novedad/{tipo.pk}/",
        {"nombre": "Licencia / certificado", "activo": False},
        format="json",
    )
    assert cambio_editorial.status_code == 200, cambio_editorial.data
    assert cambio_editorial.data["nombre"] == "Licencia / certificado"
    assert cambio_editorial.data["activo"] is False


def test_semantica_puede_corregirse_antes_del_primer_uso(cliente_rrhh):
    tipo = TipoNovedad.objects.create(
        codigo="PERMISO",
        nombre="Permiso",
        ocupa_periodo=False,
    )

    resp = cliente_rrhh.patch(
        f"/api/v1/tipos-novedad/{tipo.pk}/",
        {"ocupa_periodo": True},
        format="json",
    )

    assert resp.status_code == 200, resp.data
    tipo.refresh_from_db()
    assert tipo.ocupa_periodo is True
