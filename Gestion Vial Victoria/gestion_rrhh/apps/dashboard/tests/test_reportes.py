"""Tests de la pantalla Reportes: dotación en el tiempo, ausentismo por tipo y
motivos de egreso.

El selector se prueba con un `hoy` fijo (2026-07-13) para que las cuentas sean
deterministas; el endpoint se prueba por forma y scoping de rol.
"""
from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.dashboard import reportes
from apps.empleados.models import Empleado, MotivoEgreso, RelacionLaboral
from apps.novedades.models import EstadoNovedad, Novedad, TipoNovedad
from apps.organizacion.models import Empresa, Puesto, Sector
from common import roles

pytestmark = pytest.mark.django_db

HOY = date(2026, 7, 13)


@pytest.fixture
def empresa():
    empresa = Empresa.objects.create(nombre="VIAL VICTORIA")
    empresa._sector_prueba = Sector.objects.create(nombre="Operaciones")
    empresa._puesto_prueba = Puesto.objects.create(
        nombre="Chofer", sector=empresa._sector_prueba
    )
    return empresa


@pytest.fixture
def tipos():
    # ocupa_periodo=True → cuentan como ausentismo; HORAS_EXTRA (False) no.
    return {
        "FALTA": TipoNovedad.objects.create(codigo="FALTA", nombre="Falta", ocupa_periodo=True),
        "LICENCIA_MEDICA": TipoNovedad.objects.create(
            codigo="LICENCIA_MEDICA", nombre="Licencia médica",
            ocupa_periodo=True, admite_prorroga=True,
        ),
        "VACACIONES": TipoNovedad.objects.create(
            codigo="VACACIONES", nombre="Vacaciones", ocupa_periodo=True,
        ),
        "HORAS_EXTRA": TipoNovedad.objects.create(
            codigo="HORAS_EXTRA", nombre="Horas extra", requiere_cantidad_horas=True,
        ),
    }


def _emp(empresa, legajo, dni, nombre, apellido, ingreso, egreso=None, motivo=""):
    e = Empleado.objects.create(legajo=legajo, dni=dni, nombre=nombre, apellido=apellido)
    RelacionLaboral.objects.create(
        empleado=e,
        empresa=empresa,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        fecha_ingreso=ingreso,
        fecha_egreso=egreso,
        motivo_egreso=(motivo or MotivoEgreso.RENUNCIA) if egreso else "",
        estado="FINALIZADA" if egreso else "ACTIVA",
    )
    return e


def test_dotacion_serie_de_12_meses_y_total_por_estado(empresa):
    _emp(empresa, "0001", "30111001", "Ana", "Uno", date(2024, 1, 10))     # activa siempre
    _emp(empresa, "0002", "30111002", "Beto", "Dos", date(2026, 7, 5))     # ingresó este mes
    # baja este mes: cuenta activa a fin de junio, no a hoy
    _emp(empresa, "0003", "30111003", "Cira", "Tres", date(2020, 1, 1),
         egreso=date(2026, 7, 10), motivo=MotivoEgreso.RENUNCIA)

    dot = reportes.metricas_reportes(hoy=HOY)["dotacion"]
    assert len(dot["serie"]) == 12
    assert dot["serie"][-1]["label"] == "Jul"          # el último punto es el mes actual
    assert dot["total"] == 2                            # Ana y Beto ACTIVAS hoy; Cira finalizó
    # A fin de junio estaban Ana y Cira (Beto aún no ingresaba): serie del mes previo = 2.
    assert dot["serie"][-2]["valor"] == 2


def test_dotacion_variacion_porcentual_vs_hace_12_meses(empresa):
    # Base hace 12 meses (julio 2025): solo Ana. Hoy: Ana + Beto → +100%.
    _emp(empresa, "0001", "30111001", "Ana", "Uno", date(2024, 1, 10))
    _emp(empresa, "0002", "30111002", "Beto", "Dos", date(2026, 3, 1))

    dot = reportes.metricas_reportes(hoy=HOY)["dotacion"]
    assert dot["total"] == 2
    assert dot["delta_pct"] == pytest.approx(100.0)


def test_ausentismo_por_tipo_solo_ocupa_periodo_y_sin_anuladas(empresa, tipos):
    e = _emp(empresa, "0001", "30111001", "Ana", "Uno", date(2024, 1, 1))
    rel = e.relaciones.first()

    def nov(tipo, desde, estado=EstadoNovedad.REGISTRADA, origen=None):
        # Día único (fecha_hasta = fecha_desde) para no solapar el ExclusionConstraint de
        # novedades que ocupan período en el mismo empleado.
        return Novedad.objects.create(
            empleado=e, relacion_laboral=rel, tipo_novedad=tipo,
            fecha_desde=desde,
            fecha_hasta=desde,
            estado=estado,
            motivo_anulacion="Dato de prueba" if estado == EstadoNovedad.ANULADA else "",
            novedad_origen=origen,
        )

    madre = nov(tipos["FALTA"], date(2026, 3, 1))
    nov(tipos["FALTA"], date(2026, 5, 1))
    nov(tipos["LICENCIA_MEDICA"], date(2026, 2, 1))
    nov(tipos["HORAS_EXTRA"], date(2026, 4, 1))                    # no ocupa período → excluida
    nov(tipos["FALTA"], date(2026, 6, 1), estado=EstadoNovedad.ANULADA)  # excluida
    nov(tipos["FALTA"], date(2025, 12, 1))                         # año anterior → excluida
    nov(tipos["LICENCIA_MEDICA"], date(2026, 3, 15), origen=madre)  # prórroga → no cuenta

    aus = reportes.metricas_reportes(hoy=HOY)["ausentismo"]
    assert aus["anio"] == 2026
    assert aus["total"] == 3                                       # 2 faltas + 1 licencia
    items = {i["label"]: i for i in aus["items"]}
    assert items["Falta"]["cantidad"] == 2
    assert items["Licencia médica"]["cantidad"] == 1
    assert "Horas extra" not in items
    assert items["Falta"]["pct"] == 67                             # 2/3 redondeado


def test_reporte_anual_incluye_madre_del_anio_anterior_extendida_en_el_actual(
    empresa,
    tipos,
):
    empleado = _emp(
        empresa,
        "EXT-2",
        "40111992",
        "Reporte",
        "Extendido",
        date(2024, 1, 1),
    )
    relacion = empleado.relaciones.get()
    madre = Novedad.objects.create(
        empleado=empleado,
        relacion_laboral=relacion,
        tipo_novedad=tipos["LICENCIA_MEDICA"],
        fecha_desde=date(2025, 12, 20),
        fecha_hasta=date(2025, 12, 31),
        estado=EstadoNovedad.APROBADA,
    )
    Novedad.objects.create(
        empleado=empleado,
        relacion_laboral=relacion,
        tipo_novedad=tipos["LICENCIA_MEDICA"],
        fecha_desde=date(2026, 1, 1),
        fecha_hasta=date(2026, 1, 10),
        estado=EstadoNovedad.CERRADA,
        novedad_origen=madre,
    )

    resultado = reportes.metricas_reportes(hoy=HOY)["ausentismo"]

    assert resultado["total"] == 1
    assert resultado["items"] == [
        {"label": "Licencia médica", "cantidad": 1, "pct": 100}
    ]


def test_motivos_de_egreso_ultimos_12_meses(empresa):
    _emp(empresa, "0001", "30111001", "Ana", "Uno", date(2020, 1, 1),
         egreso=date(2026, 6, 1), motivo=MotivoEgreso.RENUNCIA)
    _emp(empresa, "0002", "30111002", "Beto", "Dos", date(2020, 1, 1),
         egreso=date(2026, 5, 1), motivo=MotivoEgreso.RENUNCIA)
    _emp(empresa, "0003", "30111003", "Cira", "Tres", date(2020, 1, 1),
         egreso=date(2026, 2, 1), motivo=MotivoEgreso.DESPIDO)
    # egreso hace más de 12 meses → fuera de la ventana
    _emp(empresa, "0004", "30111004", "Dan", "Cuatro", date(2018, 1, 1),
         egreso=date(2025, 1, 1), motivo=MotivoEgreso.JUBILACION)

    egr = reportes.metricas_reportes(hoy=HOY)["egresos"]
    assert egr["total"] == 3
    items = {i["label"]: i for i in egr["items"]}
    assert items["Renuncia"]["cantidad"] == 2
    assert items["Despido"]["cantidad"] == 1
    assert "Jubilación" not in items                               # fuera de la ventana
    assert egr["items"][0]["label"] == "Renuncia"                 # ordenado por cantidad desc
    assert items["Renuncia"]["pct"] == 67


def test_endpoint_requiere_rol_dotacion(crear_usuario):
    cli = APIClient()
    cli.force_authenticate(crear_usuario(username="emp", rol=roles.EMPLEADO))
    assert cli.get("/api/v1/reportes/metricas/").status_code == 403


def test_endpoint_rrhh_devuelve_forma(crear_usuario, empresa):
    cli = APIClient()
    cli.force_authenticate(crear_usuario(username="rh", rol=roles.RRHH))
    resp = cli.get("/api/v1/reportes/metricas/")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"dotacion", "ausentismo", "egresos"}
    assert set(body["dotacion"]) == {"total", "delta_pct", "serie"}
    assert set(body["ausentismo"]) == {"anio", "total", "items"}
    assert set(body["egresos"]) == {"total", "items"}
