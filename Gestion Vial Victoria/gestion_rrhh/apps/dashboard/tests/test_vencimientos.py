"""Vencimientos de la dotación (CU-07): qué cuenta como alerta y qué no.

`hoy` fijo para que el semáforo sea determinista: un test que dependa de la fecha real
empieza a fallar solo el día que un vencimiento cruza el umbral.
"""
from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from apps.dashboard.vencimientos import GRUPO_CONTRATOS, vencimientos_de_la_dotacion
from apps.empleados.models import (
    DocumentoEmpleado,
    Empleado,
    EstadoRelacion,
    RelacionLaboral,
    TipoContrato,
    TipoDocumento,
)
from apps.organizacion.models import Empresa, Parametro
from apps.organizacion.selectors import CLAVE_DIAS_AVISO
from common import roles

pytestmark = pytest.mark.django_db

HOY = date(2026, 7, 13)


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="VIAL VICTORIA")


@pytest.fixture
def apto():
    return TipoDocumento.objects.create(nombre="Apto médico")


def _empleado(dni, apellido, empresa, *, activo=True, **rel):
    emp = Empleado.objects.create(legajo=dni[-4:], dni=dni, nombre="Test", apellido=apellido)
    RelacionLaboral.objects.create(
        empleado=emp,
        empresa=empresa,
        fecha_ingreso=date(2024, 1, 10),
        estado=EstadoRelacion.ACTIVA if activo else EstadoRelacion.FINALIZADA,
        fecha_egreso=None if activo else date(2025, 1, 1),
        **rel,
    )
    return emp


def _items(data, tipo):
    for grupo in data["grupos"]:
        if grupo["tipo"] == tipo:
            return grupo["items"]
    return []


def _apellidos(items):
    return {i["empleado"].split()[-1]: i for i in items}


def test_el_semaforo_marca_vencido_por_vencer_y_al_dia(empresa, apto):
    """El umbral es inclusivo: lo que vence el último día del aviso YA es "por vencer".
    Si fuera exclusivo, ese documento se vería en verde hasta el día siguiente."""
    casos = {
        "Vencido": HOY - timedelta(days=1),
        "Justo": HOY,                          # vence hoy: todavía no venció
        "Limite": HOY + timedelta(days=30),    # último día del aviso
        "Lejano": HOY + timedelta(days=31),    # un día más: al día
    }
    for numero, (apellido, vence) in enumerate(casos.items()):
        emp = _empleado(f"3011122{numero}", apellido, empresa)
        DocumentoEmpleado.objects.create(
            empleado=emp, tipo_documento=apto, fecha_vencimiento=vence
        )

    items = _apellidos(_items(vencimientos_de_la_dotacion(hoy=HOY), "Apto médico"))
    assert {k: v["estado"] for k, v in items.items()} == {
        "Vencido": "bad", "Justo": "warn", "Limite": "warn", "Lejano": "ok"
    }


def test_no_alerta_por_quien_ya_no_trabaja(empresa, apto):
    """Un carnet vencido de alguien que se fue hace dos años no es un problema: es historia.
    Si contara, la lista se llenaría de ruido que nadie puede accionar."""
    activo = _empleado("30111222", "Activo", empresa)
    egresado = _empleado("30222333", "Egresado", empresa, activo=False)
    for emp in (activo, egresado):
        DocumentoEmpleado.objects.create(
            empleado=emp, tipo_documento=apto, fecha_vencimiento=HOY - timedelta(days=5)
        )

    data = vencimientos_de_la_dotacion(hoy=HOY)
    assert [i["empleado"] for i in _items(data, "Apto médico")] == ["Test Activo"]
    assert data["resumen"]["vencidos"] == 1


def test_el_documento_sin_vencimiento_no_es_alerta(empresa, apto):
    """Sin fecha no hay nada que vigilar: el contrato firmado no vence."""
    emp = _empleado("30111222", "Sinfecha", empresa)
    DocumentoEmpleado.objects.create(empleado=emp, tipo_documento=apto, fecha_vencimiento=None)
    data = vencimientos_de_la_dotacion(hoy=HOY)
    assert data["grupos"] == []
    assert data["resumen"] == {"vencidos": 0, "por_vencer": 0, "al_dia": 0}


def test_el_indeterminado_no_vence_pero_el_plazo_fijo_sin_fecha_alerta(empresa):
    """Un plazo fijo sin fecha de fin NO está al día: está sin control, y es justo lo que hay
    que revisar. El indeterminado, en cambio, no termina: no hay nada que avisar."""
    _empleado("30111222", "Indeterminado", empresa, tipo_contrato=TipoContrato.INDETERMINADO)
    _empleado("30222333", "SinFecha", empresa, tipo_contrato=TipoContrato.PLAZO_FIJO)
    _empleado(
        "30333444", "ConFecha", empresa,
        tipo_contrato=TipoContrato.PLAZO_FIJO,
        fecha_vencimiento_contrato=HOY + timedelta(days=10),
    )

    items = _items(vencimientos_de_la_dotacion(hoy=HOY), GRUPO_CONTRATOS)
    por_apellido = _apellidos(items)
    assert "Indeterminado" not in por_apellido
    assert (por_apellido["SinFecha"]["estado"], por_apellido["SinFecha"]["fecha"]) == ("bad", None)
    assert por_apellido["ConFecha"]["estado"] == "warn"
    # Lo que no tiene fecha va primero: es lo más urgente de revisar.
    assert items[0]["empleado"].endswith("SinFecha")


def test_cada_tipo_avisa_con_su_propia_anticipacion(empresa, apto):
    """El apto puede querer más margen que el carnet: el umbral es del tipo, no global.
    Con un umbral único, estos dos documentos —que vencen el MISMO día— saldrían iguales."""
    carnet = TipoDocumento.objects.create(nombre="Carnet", dias_aviso=30)
    apto.dias_aviso = 60
    apto.save()
    emp = _empleado("30111222", "Alguien", empresa)
    vence = HOY + timedelta(days=45)  # dentro del aviso del apto, fuera del de carnet
    DocumentoEmpleado.objects.create(empleado=emp, tipo_documento=apto, fecha_vencimiento=vence)
    DocumentoEmpleado.objects.create(empleado=emp, tipo_documento=carnet, fecha_vencimiento=vence)

    data = vencimientos_de_la_dotacion(hoy=HOY)
    assert _items(data, "Apto médico")[0]["estado"] == "warn"
    assert _items(data, "Carnet")[0]["estado"] == "ok"


def test_el_umbral_de_contratos_sale_del_parametro_no_del_codigo(empresa):
    """El 45 estaba hardcodeado en el front, donde nadie podía cambiarlo sin un deploy."""
    _empleado(
        "30111222", "Lejano", empresa,
        tipo_contrato=TipoContrato.PLAZO_FIJO,
        fecha_vencimiento_contrato=HOY + timedelta(days=45),
    )
    # Con el default (30 días), 45 días es "al día".
    assert vencimientos_de_la_dotacion(hoy=HOY)["resumen"] == {
        "vencidos": 0, "por_vencer": 0, "al_dia": 1
    }

    Parametro.objects.create(clave=CLAVE_DIAS_AVISO, valor={"dias": 60})
    assert vencimientos_de_la_dotacion(hoy=HOY)["resumen"] == {
        "vencidos": 0, "por_vencer": 1, "al_dia": 0
    }


def test_un_parametro_roto_no_tira_abajo_la_alerta(empresa):
    """Alguien escribe cualquier cosa en el admin: el aviso cae al default, no se cae."""
    _empleado(
        "30111222", "Alguien", empresa,
        tipo_contrato=TipoContrato.PLAZO_FIJO,
        fecha_vencimiento_contrato=HOY + timedelta(days=10),
    )
    for basura in ({"dias": "muchos"}, {"otra_clave": 5}, {}, {"dias": -5}, {"dias": 9999}):
        Parametro.objects.update_or_create(clave=CLAVE_DIAS_AVISO, defaults={"valor": basura})
        data = vencimientos_de_la_dotacion(hoy=HOY)
        assert data["resumen"]["por_vencer"] == 1, basura


def test_dos_empresas_no_duplican_el_documento(empresa, apto):
    """El carnet es de la persona, no de la empresa: quien trabaja en las dos empresas del
    grupo tiene UN carnet, no dos. El JOIN con relaciones lo duplicaría."""
    otra = Empresa.objects.create(nombre="PREMOCOR")
    emp = _empleado("30111222", "Doble", empresa)
    RelacionLaboral.objects.create(
        empleado=emp, empresa=otra, fecha_ingreso=date(2025, 1, 1), estado=EstadoRelacion.ACTIVA
    )
    DocumentoEmpleado.objects.create(
        empleado=emp, tipo_documento=apto, fecha_vencimiento=HOY + timedelta(days=5)
    )
    items = _items(vencimientos_de_la_dotacion(hoy=HOY), "Apto médico")
    assert len(items) == 1, "el documento aparece repetido por cada relación activa"


# ---------- Endpoint ----------
def test_el_endpoint_lo_ve_rrhh_y_no_el_empleado(crear_usuario, empresa, apto):
    emp = _empleado("30111222", "Alguien", empresa)
    DocumentoEmpleado.objects.create(
        empleado=emp, tipo_documento=apto, fecha_vencimiento=HOY + timedelta(days=5)
    )
    rrhh = APIClient()
    rrhh.force_authenticate(crear_usuario(username="rrhh", rol=roles.RRHH))
    resp = rrhh.get("/api/v1/alertas/vencimientos/")
    assert resp.status_code == 200
    assert set(resp.data) == {"resumen", "grupos"}

    # El empleado no tiene panel: la dotación entera no es asunto suyo.
    empleado = APIClient()
    empleado.force_authenticate(crear_usuario(username="pepe", rol=roles.EMPLEADO))
    assert empleado.get("/api/v1/alertas/vencimientos/").status_code == 403
    assert APIClient().get("/api/v1/alertas/vencimientos/").status_code == 401
