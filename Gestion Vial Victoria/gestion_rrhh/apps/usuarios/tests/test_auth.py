import pytest

pytestmark = pytest.mark.django_db


def test_login_devuelve_tokens(api_client, crear_usuario):
    crear_usuario(username="luciana", password="clave-segura-123")
    resp = api_client.post(
        "/api/v1/auth/token/",
        {"username": "luciana", "password": "clave-segura-123"},
        format="json",
    )
    assert resp.status_code == 200
    assert "access" in resp.data and "refresh" in resp.data


def test_login_invalido_da_401(api_client, crear_usuario):
    crear_usuario(username="luciana")
    resp = api_client.post(
        "/api/v1/auth/token/",
        {"username": "luciana", "password": "incorrecta"},
        format="json",
    )
    assert resp.status_code == 401
    assert resp.data["codigo"]  # formato de error uniforme (§8)


def test_mi_perfil_devuelve_roles(cliente_rrhh):
    resp = cliente_rrhh.get("/api/v1/mi/perfil/")
    assert resp.status_code == 200
    assert resp.data["username"] == "rrhh"
    assert "RRHH" in resp.data["roles"]


def test_mi_perfil_requiere_auth(api_client):
    resp = api_client.get("/api/v1/mi/perfil/")
    assert resp.status_code == 401
