"""Tests del panel general: cálculo de métricas (selector) y permisos del endpoint.

El selector se prueba con un `hoy` fijo (2026-07-13) para que las cuentas sean
deterministas; el endpoint se prueba por forma y scoping de rol.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.dashboard import selectors
from apps.empleados.models import Empleado, RelacionLaboral
from apps.novedades.models import EstadoNovedad, Novedad, TipoNovedad
from apps.organizacion.models import Empresa
from common import roles

pytestmark = pytest.mark.django_db

HOY = date(2026, 7, 13)


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="VIAL VICTORIA")


@pytest.fixture
def tipos():
    return {
        "FALTA": TipoNovedad.objects.create(codigo="FALTA", nombre="Falta"),
        "LICENCIA_MEDICA": TipoNovedad.objects.create(
            codigo="LICENCIA_MEDICA", nombre="Licencia médica",
            justifica_ausencia=True, requiere_certificado=True, admite_prorroga=True,
        ),
        "ACCIDENTE": TipoNovedad.objects.create(
            codigo="ACCIDENTE", nombre="Accidente / ART", justifica_ausencia=True,
        ),
        "VACACIONES": TipoNovedad.objects.create(
            codigo="VACACIONES", nombre="Vacaciones", justifica_ausencia=True,
        ),
    }


@pytest.fixture
def escenario(empresa, tipos):
    """Dotación y novedades con fechas elegidas alrededor de julio 2026."""
    def _emp(legajo, dni, nombre, apellido, ingreso, egreso=None):
        e = Empleado.objects.create(legajo=legajo, dni=dni, nombre=nombre, apellido=apellido)
        rel = RelacionLaboral.objects.create(
            empleado=e, empresa=empresa, fecha_ingreso=ingreso, fecha_egreso=egreso,
            estado="FINALIZADA" if egreso else "ACTIVA",
        )
        return e, rel

    e1, r1 = _emp("0001", "30111001", "Ana", "Uno", date(2024, 1, 10))       # activa siempre
    e2, r2 = _emp("0002", "30111002", "Beto", "Dos", date(2026, 7, 5))       # ingreso del mes
    e3, r3 = _emp("0003", "30111003", "Cira", "Tres", date(2020, 1, 1), date(2026, 7, 10))
    e4, r4 = _emp("0004", "30111004", "Dan", "Cuatro", date(2026, 6, 15))    # ingreso mes anterior

    def _nov(emp, rel, tipo, desde, estado=EstadoNovedad.REGISTRADA):
        return Novedad.objects.create(
            empleado=emp, relacion_laboral=rel, tipo_novedad=tipo,
            fecha_desde=desde, estado=estado,
        )

    _nov(e1, r1, tipos["FALTA"], date(2026, 7, 2))
    _nov(e1, r1, tipos["FALTA"], date(2026, 7, 9))
    _nov(e2, r2, tipos["LICENCIA_MEDICA"], date(2026, 7, 3))
    _nov(e4, r4, tipos["ACCIDENTE"], date(2026, 7, 4))
    _nov(e4, r4, tipos["VACACIONES"], date(2026, 7, 5))                      # no cuenta
    _nov(e2, r2, tipos["FALTA"], date(2026, 7, 1), estado=EstadoNovedad.ANULADA)  # excluida
    _nov(e1, r1, tipos["FALTA"], date(2026, 6, 10))                          # mes anterior
    return locals()


def test_kpis_del_mes(escenario):
    m = selectors.metricas_dashboard(hoy=HOY)
    assert m["activos"] == {"valor": 3, "delta": 0}          # E1,E2,E4 hoy; E1,E3,E4 fin junio
    assert m["ingresos_mes"] == {"valor": 1, "delta": 0}     # E2 en julio; E4 en junio
    assert m["egresos_mes"] == {"valor": 1, "delta": 1}      # E3 en julio; 0 en junio
    assert m["ausentismo_mes"] == {"valor": 4, "delta": 3}   # 4 en julio (sin vac/anulada); 1 junio


def test_activos_ignora_finalizada_con_egreso_futuro(empresa):
    """Regresión: una relación FINALIZADA no cuenta como activa aunque su egreso sea
    futuro (baja con egreso diferido). El KPI usa `estado`, no las fechas."""
    activa = Empleado.objects.create(
        legajo="9001", dni="40111001", nombre="Vale", apellido="Activa"
    )
    RelacionLaboral.objects.create(
        empleado=activa, empresa=empresa, fecha_ingreso=date(2024, 1, 1), estado="ACTIVA",
    )
    baja = Empleado.objects.create(legajo="9002", dni="40111002", nombre="Bruno", apellido="Baja")
    RelacionLaboral.objects.create(  # dada de baja, pero con egreso mañana
        empleado=baja, empresa=empresa, fecha_ingreso=HOY, fecha_egreso=date(2026, 7, 14),
        estado="FINALIZADA",
    )
    m = selectors.metricas_dashboard(hoy=HOY)
    assert m["activos"]["valor"] == 1  # solo la ACTIVA; la FINALIZADA no cuenta


def test_ranking_faltas_solo_faltas_validas(escenario):
    m = selectors.metricas_dashboard(hoy=HOY)
    ranking = m["ranking_faltas"]
    assert ranking[0]["nombre"] == "Ana Uno"
    assert ranking[0]["total"] == 2
    assert ranking[0]["empresa"] == "VIAL VICTORIA"
    # la falta anulada de Beto no aparece
    assert all(r["nombre"] != "Beto Dos" for r in ranking)


def test_ranking_faltas_resuelve_empresa_sin_relacion_en_la_falta(empresa, tipos):
    """Regresión (bug Cardoso): una falta con relacion_laboral=NULL (dato importado
    fuera del alta) no debe mostrar '—'; la empresa se resuelve por la relación del
    empleado, no por la FK de la falta."""
    e = Empleado.objects.create(
        legajo="7001", dni="41111001", nombre="Agus", apellido="Cardoso"
    )
    RelacionLaboral.objects.create(
        empleado=e, empresa=empresa, fecha_ingreso=date(2024, 1, 1), estado="ACTIVA",
    )
    Novedad.objects.create(  # sin relación asociada a propósito
        empleado=e, relacion_laboral=None, tipo_novedad=tipos["FALTA"],
        fecha_desde=date(2026, 7, 8), estado=EstadoNovedad.REGISTRADA,
    )
    m = selectors.metricas_dashboard(hoy=HOY)
    fila = next(r for r in m["ranking_faltas"] if r["nombre"] == "Agus Cardoso")
    assert fila["empresa"] == "VIAL VICTORIA"
    assert fila["total"] == 1


def test_rotacion_tiene_mensual_anual_y_serie(escenario):
    m = selectors.metricas_dashboard(hoy=HOY)
    rot = m["rotacion"]
    assert set(rot["mensual"]) == {"valor", "delta_pts"}
    assert set(rot["anual"]) == {"valor", "delta_pts"}
    assert len(rot["serie"]) == 12
    assert rot["serie"][-1]["label"] == "Jul"        # el último punto es el mes actual
    # rotación mensual: (ingresos 1 + egresos 1)/2 = 1 sobre dotación media 3 = 33.3%
    assert rot["mensual"]["valor"] == pytest.approx(33.3, abs=0.1)


def test_endpoint_requiere_rol_dotacion(crear_usuario):
    cli_emp = APIClient()
    cli_emp.force_authenticate(crear_usuario(username="emp", rol=roles.EMPLEADO))
    assert cli_emp.get("/api/v1/dashboard/metricas/").status_code == 403


def test_endpoint_rrhh_devuelve_forma(crear_usuario, escenario):
    cli = APIClient()
    cli.force_authenticate(crear_usuario(username="rh", rol=roles.RRHH))
    resp = cli.get("/api/v1/dashboard/metricas/")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {
        "periodo", "activos", "ingresos_mes", "egresos_mes",
        "ausentismo_mes", "rotacion", "ranking_faltas",
    }
