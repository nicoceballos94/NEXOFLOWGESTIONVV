"""Alertas del día: qué llega a la tarjeta del panel, en qué orden y qué no.

`hoy` fijo: un test que dependa de la fecha real empieza a fallar solo el día que algo cruza
un umbral (y el de cumpleaños, exactamente una vez por año).
"""
from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from apps.dashboard.alertas_dia import MAX_ITEMS, alertas_del_dia, fecha_larga
from apps.empleados.models import (
    DocumentoEmpleado,
    Empleado,
    EstadoRelacion,
    RelacionLaboral,
    TipoContrato,
    TipoDocumento,
)
from apps.novedades.models import EstadoNovedad, Novedad, TipoNovedad
from apps.organizacion.models import Empresa
from common import roles

pytestmark = pytest.mark.django_db

HOY = date(2026, 7, 15)  # miércoles


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="VIAL VICTORIA")


@pytest.fixture
def apto():
    return TipoDocumento.objects.create(nombre="Apto médico", dias_aviso=30)


def _empleado(dni, apellido, empresa, *, activo=True, nace=None):
    emp = Empleado.objects.create(
        legajo=dni[-4:], dni=dni, nombre="Test", apellido=apellido, fecha_nacimiento=nace
    )
    RelacionLaboral.objects.create(
        empleado=emp,
        empresa=empresa,
        fecha_ingreso=date(2024, 1, 10),
        estado=EstadoRelacion.ACTIVA if activo else EstadoRelacion.FINALIZADA,
        fecha_egreso=None if activo else date(2025, 1, 1),
    )
    return emp


def _titulos(data):
    return [i["title"] for i in data["items"]]


def _textos(data):
    return [i["text"] for i in data["items"]]


def test_la_fecha_del_subtitulo_ya_no_esta_congelada():
    """El diseño decía "Viernes 4 de julio, 2026" fijo en el markup, para siempre."""
    assert fecha_larga(HOY) == "Miércoles 15 de julio, 2026"
    assert fecha_larga(date(2026, 1, 1)) == "Jueves 1 de enero, 2026"


def test_dice_cuanto_falta_o_cuanto_hace_que_vencio(empresa, apto):
    """La fecha sola no dice qué tan urgente es: "vence en 3 días" sí."""
    casos = {
        "Vencio": (HOY - timedelta(days=3), "venció hace 3 días (12/07)"),
        "Ayer": (HOY - timedelta(days=1), "venció hace 1 día (14/07)"),
        "Hoy": (HOY, "vence hoy (15/07)"),
        "Manana": (HOY + timedelta(days=1), "vence en 1 día (16/07)"),
        "Pronto": (HOY + timedelta(days=5), "vence en 5 días (20/07)"),
    }
    for numero, (apellido, (vence, _)) in enumerate(casos.items()):
        emp = _empleado(f"3011122{numero}", apellido, empresa)
        DocumentoEmpleado.objects.create(empleado=emp, tipo_documento=apto, fecha_vencimiento=vence)

    textos = " | ".join(_textos(alertas_del_dia(hoy=HOY)))
    for apellido, (_, esperado) in casos.items():
        assert esperado in textos, f"{apellido}: falta '{esperado}'"


def test_contrato_a_plazo_sin_fecha_se_rotula_sin_fecha_no_vencido(empresa):
    """Un plazo fijo sin fecha de fin es alerta roja, pero el título no dice "vencido" —no se
    sabe cuándo vence, es documentación incompleta—: dice "sin fecha". Y el grupo es
    "Contrato a plazo", que no se confunde con el tipo de documento "Contrato" (MEDIO-05)."""
    emp = Empleado.objects.create(legajo="9001", dni="40999001", nombre="Test", apellido="SinFin")
    RelacionLaboral.objects.create(
        empleado=emp,
        empresa=empresa,
        fecha_ingreso=date(2024, 1, 10),
        estado=EstadoRelacion.ACTIVA,
        tipo_contrato=TipoContrato.PLAZO_FIJO,
        fecha_vencimiento_contrato=None,
    )
    data = alertas_del_dia(hoy=HOY)
    assert "Contrato a plazo sin fecha" in _titulos(data)
    assert "Contrato a plazo vencido" not in _titulos(data)
    item = next(i for i in data["items"] if i["title"] == "Contrato a plazo sin fecha")
    assert item["estado"] == "bad"  # sigue siendo alerta roja


def test_lo_urgente_va_primero(empresa, apto):
    """Un cumpleaños no puede tapar un apto vencido: se ordena por urgencia, no por fecha."""
    cumple = _empleado("30111222", "Cumple", empresa, nace=date(1990, HOY.month, HOY.day))
    por_vencer = _empleado("30222333", "PorVencer", empresa)
    vencido = _empleado("30333444", "Vencido", empresa)
    DocumentoEmpleado.objects.create(
        empleado=por_vencer, tipo_documento=apto, fecha_vencimiento=HOY + timedelta(days=5)
    )
    DocumentoEmpleado.objects.create(
        empleado=vencido, tipo_documento=apto, fecha_vencimiento=HOY - timedelta(days=5)
    )
    assert cumple  # el cumpleañero existe, pero va último

    assert [i["estado"] for i in alertas_del_dia(hoy=HOY)["items"]] == ["bad", "warn", "info"]
    assert _titulos(alertas_del_dia(hoy=HOY)) == [
        "Apto médico vencido", "Apto médico próximo a vencer", "Cumpleaños del día"
    ]


def test_el_que_esta_al_dia_no_es_alerta(empresa, apto):
    emp = _empleado("30111222", "AlDia", empresa)
    DocumentoEmpleado.objects.create(
        empleado=emp, tipo_documento=apto, fecha_vencimiento=HOY + timedelta(days=90)
    )
    data = alertas_del_dia(hoy=HOY)
    assert data["items"] == []
    assert data["total"] == 0


def test_el_cumpleanos_es_del_dia_no_del_mes(empresa):
    """Filtrar por mes mostraría 30 cumpleaños; por año, ninguno (nadie nació en 2026)."""
    _empleado("30111222", "Hoy", empresa, nace=date(1990, HOY.month, HOY.day))
    _empleado("30222333", "Manana", empresa, nace=date(1990, HOY.month, HOY.day + 1))
    _empleado("30333444", "OtroMes", empresa, nace=date(1990, HOY.month - 1, HOY.day))
    _empleado("30444555", "SinFecha", empresa, nace=None)

    data = alertas_del_dia(hoy=HOY)
    assert _textos(data) == ["Test Hoy cumple años hoy"]


def test_varios_cumpleanos_se_resumen_en_una_linea(empresa):
    """Tres nombres en una tarjeta de resumen la rompen: se agrupan."""
    for numero in range(3):
        _empleado(f"3011122{numero}", f"Emp{numero}", empresa, nace=date(1990, HOY.month, HOY.day))
    data = alertas_del_dia(hoy=HOY)
    assert _textos(data) == ["Test Emp0 y 2 más cumplen años hoy"]


def test_el_cumpleanos_de_un_egresado_no_se_saluda(empresa):
    _empleado("30111222", "Egresado", empresa, activo=False, nace=date(1990, HOY.month, HOY.day))
    assert alertas_del_dia(hoy=HOY)["items"] == []


# ---------- Certificados ----------
@pytest.fixture
def licencia():
    return TipoNovedad.objects.create(
        codigo="LICENCIA_MEDICA", nombre="Licencia médica", requiere_certificado=True
    )


@pytest.fixture
def vacaciones():
    return TipoNovedad.objects.create(
        codigo="VACACIONES", nombre="Vacaciones", requiere_certificado=False
    )


def _novedad(emp, tipo, desde, **kw):
    return Novedad.objects.create(
        empleado=emp,
        tipo_novedad=tipo,
        fecha_desde=desde,
        fecha_hasta=kw.pop("hasta", desde),
        estado=kw.pop("estado", EstadoNovedad.APROBADA),
        **kw,
    )


def test_avisa_del_certificado_que_falta(empresa, licencia):
    emp = _empleado("30111222", "Ojeda", empresa)
    _novedad(emp, licencia, HOY - timedelta(days=17))
    data = alertas_del_dia(hoy=HOY)
    assert _titulos(data) == ["Certificado pendiente"]
    assert _textos(data) == ["Test Ojeda — licencia médica 28/06 sin certificado"]


def test_no_avisa_por_certificados_que_no_faltan(empresa, licencia, vacaciones):
    """Cuatro razones distintas para no alertar; todas terminan en la misma lista vacía."""
    presentado = _empleado("30111222", "Presentado", empresa)
    _novedad(presentado, licencia, HOY - timedelta(days=5), certificado_recibido_en=HOY)

    no_requiere = _empleado("30222333", "NoRequiere", empresa)
    _novedad(no_requiere, vacaciones, HOY - timedelta(days=5))

    futura = _empleado("30333444", "Futura", empresa)
    _novedad(futura, licencia, HOY + timedelta(days=3), hasta=HOY + timedelta(days=5))

    egresado = _empleado("30555666", "Egresado", empresa, activo=False)
    _novedad(egresado, licencia, HOY - timedelta(days=5))

    assert alertas_del_dia(hoy=HOY)["items"] == []


def test_la_novedad_anulada_o_rechazada_no_reclama_certificado(empresa, licencia):
    """La rechazada nunca pasó y la anulada se borra de los hechos: su certificado no falta."""
    for numero, estado in enumerate((EstadoNovedad.ANULADA, EstadoNovedad.RECHAZADA)):
        emp = _empleado(f"3011122{numero}", f"Emp{numero}", empresa)
        _novedad(emp, licencia, HOY - timedelta(days=5), estado=estado)
    assert alertas_del_dia(hoy=HOY)["items"] == []

    # Control: la misma novedad aprobada SÍ alerta (si no, el test pasaría por otra razón).
    emp = _empleado("30999888", "Aprobada", empresa)
    _novedad(emp, licencia, HOY - timedelta(days=5), estado=EstadoNovedad.APROBADA)
    assert len(alertas_del_dia(hoy=HOY)["items"]) == 1


def test_la_tarjeta_se_recorta_pero_el_total_no_miente(empresa, apto):
    """La tarjeta es un resumen: muestra 6 de 9 y dice que son 9."""
    for numero in range(9):
        emp = _empleado(f"301112{numero:02d}", f"Emp{numero}", empresa)
        DocumentoEmpleado.objects.create(
            empleado=emp, tipo_documento=apto, fecha_vencimiento=HOY - timedelta(days=numero + 1)
        )
    data = alertas_del_dia(hoy=HOY)
    assert len(data["items"]) == MAX_ITEMS
    assert data["total"] == 9


# ---------- Endpoint ----------
def test_el_endpoint_lo_ve_rrhh_y_no_el_empleado(crear_usuario, empresa, apto):
    emp = _empleado("30111222", "Alguien", empresa)
    DocumentoEmpleado.objects.create(
        empleado=emp, tipo_documento=apto, fecha_vencimiento=HOY - timedelta(days=1)
    )
    rrhh = APIClient()
    rrhh.force_authenticate(crear_usuario(username="rrhh", rol=roles.RRHH))
    resp = rrhh.get("/api/v1/alertas/del-dia/")
    assert resp.status_code == 200
    assert set(resp.data) == {"fecha", "total", "items"}

    empleado = APIClient()
    empleado.force_authenticate(crear_usuario(username="pepe", rol=roles.EMPLEADO))
    assert empleado.get("/api/v1/alertas/del-dia/").status_code == 403
    assert APIClient().get("/api/v1/alertas/del-dia/").status_code == 401
