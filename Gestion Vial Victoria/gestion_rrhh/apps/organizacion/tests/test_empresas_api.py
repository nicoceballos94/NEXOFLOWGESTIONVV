import pytest

from apps.organizacion.models import Empresa

pytestmark = pytest.mark.django_db


def test_rrhh_puede_crear_empresa(cliente_rrhh):
    resp = cliente_rrhh.post("/api/v1/empresas/", {"nombre": "VIAL VICTORIA"}, format="json")
    assert resp.status_code == 201
    assert Empresa.objects.filter(nombre="VIAL VICTORIA").exists()


def test_empleado_no_puede_crear_empresa(cliente_empleado):
    resp = cliente_empleado.post("/api/v1/empresas/", {"nombre": "OTRA SA"}, format="json")
    assert resp.status_code == 403
    assert not Empresa.objects.filter(nombre="OTRA SA").exists()


def test_empleado_puede_listar_empresas(cliente_empleado, cliente_rrhh):
    cliente_rrhh.post("/api/v1/empresas/", {"nombre": "PREMOCOR"}, format="json")
    resp = cliente_empleado.get("/api/v1/empresas/")
    assert resp.status_code == 200
    assert resp.data["count"] == 1  # respuesta paginada (§8)


def test_no_hay_delete_de_empresas(cliente_rrhh):
    resp = cliente_rrhh.post("/api/v1/empresas/", {"nombre": "PREMOCOR"}, format="json")
    empresa_id = resp.data["id"]
    resp = cliente_rrhh.delete(f"/api/v1/empresas/{empresa_id}/")
    assert resp.status_code == 405  # baja = PATCH activa=False, nunca DELETE (R10)


def test_nombre_duplicado_devuelve_error_uniforme(cliente_rrhh):
    cliente_rrhh.post("/api/v1/empresas/", {"nombre": "PREMOCOR"}, format="json")
    resp = cliente_rrhh.post("/api/v1/empresas/", {"nombre": "PREMOCOR"}, format="json")
    assert resp.status_code == 400
    assert resp.data["codigo"] == "validacion"
    assert "nombre" in resp.data["campos"]
