"""Parametría de alertas (§21): qué filas se ofrecen y qué se puede guardar."""
import pytest
from rest_framework.test import APIClient

from apps.empleados.models import TipoDocumento
from apps.organizacion.config_vencimientos import (
    CLAVE_CONTRATOS,
    ClaveDesconocida,
    filas_de_configuracion,
    guardar_dias_aviso,
)
from apps.organizacion.models import Parametro
from apps.organizacion.selectors import CLAVE_DIAS_AVISO, dias_aviso_contratos
from common import roles

pytestmark = pytest.mark.django_db

URL = "/api/v1/config/vencimientos/"


@pytest.fixture
def apto():
    return TipoDocumento.objects.create(
        nombre="Apto médico", descripcion="Examen periódico."
    )


def _rrhh(crear_usuario):
    c = APIClient()
    c.force_authenticate(crear_usuario(username="rrhh", rol=roles.RRHH))
    return c


def test_un_tipo_nuevo_nace_avisando_a_30_dias(apto):
    """El estándar sin que nadie lo configure: un tipo dado de alta hoy ya avisa."""
    assert apto.dias_aviso == 30
    fila = next(f for f in filas_de_configuracion() if f["clave"] == f"tipo:{apto.id}")
    assert (fila["dias"], fila["label"], fila["hint"]) == (30, "Apto médico", "Examen periódico.")


def test_las_filas_salen_del_catalogo_mas_contratos(apto):
    """El front tenía 4 filas fijas: un tipo nuevo era invisible y no se podía configurar."""
    TipoDocumento.objects.create(nombre="Libreta sanitaria")  # tipo que el canvas no conocía
    claves = [f["clave"] for f in filas_de_configuracion()]
    labels = [f["label"] for f in filas_de_configuracion()]
    assert "Libreta sanitaria" in labels
    # Contratos va siempre y va último: no tiene catálogo detrás.
    assert claves[-1] == CLAVE_CONTRATOS


def test_un_tipo_inactivo_no_se_configura(apto):
    """Un tipo dado de baja no puede generar alertas: configurarlo no significa nada."""
    apto.activo = False
    apto.save()
    assert [f["clave"] for f in filas_de_configuracion()] == [CLAVE_CONTRATOS]
    with pytest.raises(ClaveDesconocida):
        guardar_dias_aviso(clave=f"tipo:{apto.id}", dias=10)


def test_guardar_persiste_el_tipo_y_el_contrato(apto):
    guardar_dias_aviso(clave=f"tipo:{apto.id}", dias=45)
    apto.refresh_from_db()
    assert apto.dias_aviso == 45

    guardar_dias_aviso(clave=CLAVE_CONTRATOS, dias=60)
    assert dias_aviso_contratos() == 60
    assert Parametro.objects.get(clave=CLAVE_DIAS_AVISO).valor == {"dias": 60}


def test_no_se_guarda_cualquier_cosa(apto):
    """El front clampea 0..180, pero el front no es una defensa: la API se llama sola."""
    for malo in (-1, 181, "muchos", None):
        with pytest.raises(ValueError):
            guardar_dias_aviso(clave=f"tipo:{apto.id}", dias=malo)
    apto.refresh_from_db()
    assert apto.dias_aviso == 30, "un valor inválido no debe tocar el guardado"

    for clave in ("tipo:99999", "tipo:abc", "inventada", ""):
        with pytest.raises(ClaveDesconocida):
            guardar_dias_aviso(clave=clave, dias=10)


def test_cero_es_valido(apto):
    """0 = avisar solo cuando ya venció. Es una decisión legítima, no un error."""
    guardar_dias_aviso(clave=f"tipo:{apto.id}", dias=0)
    apto.refresh_from_db()
    assert apto.dias_aviso == 0


# ---------- Endpoint ----------
def test_el_endpoint_lee_y_guarda(crear_usuario, apto):
    c = _rrhh(crear_usuario)
    resp = c.get(URL)
    assert resp.status_code == 200
    assert {f["clave"] for f in resp.data["filas"]} == {f"tipo:{apto.id}", CLAVE_CONTRATOS}

    resp = c.patch(URL, {"clave": f"tipo:{apto.id}", "dias": 45}, format="json")
    assert resp.status_code == 200
    assert resp.data["dias"] == 45
    apto.refresh_from_db()
    assert apto.dias_aviso == 45


def test_el_endpoint_rechaza_lo_invalido(crear_usuario, apto):
    """El error tiene que salir en el formato de §8: el front muestra `detalle` y un dict
    armado a mano se saltearía el manejador, dejando un "Error 400" pelado en pantalla."""
    c = _rrhh(crear_usuario)
    resp = c.patch(URL, {"clave": f"tipo:{apto.id}", "dias": 999}, format="json")
    assert resp.status_code == 400
    assert "0 a 180" in resp.data["detalle"]

    resp = c.patch(URL, {"clave": "tipo:99999", "dias": 10}, format="json")
    assert resp.status_code == 404
    assert "ya no existe" in resp.data["detalle"]


def test_solo_admin_y_rrhh_configuran(crear_usuario, apto):
    """Cambiar el umbral cambia lo que ve toda la empresa: no es de un supervisor."""
    for rol in (roles.SUPERVISOR, roles.EMPLEADO):
        c = APIClient()
        c.force_authenticate(crear_usuario(username=f"u{rol}", rol=rol))
        assert c.get(URL).status_code == 403, rol
        guardar = c.patch(URL, {"clave": CLAVE_CONTRATOS, "dias": 10}, format="json")
        assert guardar.status_code == 403, rol
    assert APIClient().get(URL).status_code == 401
