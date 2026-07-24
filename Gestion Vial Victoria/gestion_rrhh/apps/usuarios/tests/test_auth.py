import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.test import APIClient

from common import roles

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def limpiar_throttle_login():
    """Cada caso parte sin contadores de requests de otros casos del módulo."""
    cache.clear()


def test_login_crea_sesion_sin_exponer_tokens(api_client, crear_usuario):
    crear_usuario(username="luciana", password="clave-segura-123")
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"username": "luciana", "password": "clave-segura-123"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["username"] == "luciana"
    assert "access" not in resp.data and "refresh" not in resp.data
    assert "sessionid" in resp.cookies


def test_login_invalido_da_401(api_client, crear_usuario):
    crear_usuario(username="luciana")
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"username": "luciana", "password": "incorrecta"},
        format="json",
    )
    assert resp.status_code == 401
    assert resp.data["codigo"]  # formato de error uniforme (§8)


@pytest.mark.parametrize(
    "payload",
    (
        [],
        {},
        {"username": "luciana"},
        {"password": "clave-segura-123"},
        {"username": "x" * 151, "password": "clave-segura-123"},
        {"username": "luciana", "password": "x" * 1025},
    ),
)
def test_login_rechaza_entradas_malformadas_sin_error_500(api_client, payload):
    resp = api_client.post("/api/v1/auth/login/", payload, format="json")

    assert resp.status_code == 400
    assert resp.data["codigo"] == "validacion"


def test_login_bloquea_el_sexto_intento_del_mismo_origen(api_client):
    for _ in range(5):
        resp = api_client.post(
            "/api/v1/auth/login/",
            {"username": "inexistente", "password": "incorrecta"},
            format="json",
        )
        assert resp.status_code == 401

    bloqueado = api_client.post(
        "/api/v1/auth/login/",
        {"username": "inexistente", "password": "incorrecta"},
        format="json",
    )

    assert bloqueado.status_code == 429


def test_cuenta_de_servicio_no_puede_abrir_sesion_humana(api_client, crear_usuario):
    crear_usuario(
        username="n8n",
        password="clave-segura-123",
        rol=roles.SERVICIO,
    )
    resp = api_client.post(
        "/api/v1/auth/login/",
        {"username": "n8n", "password": "clave-segura-123"},
        format="json",
    )

    assert resp.status_code == 401
    assert resp.data["codigo"] == "credenciales_invalidas"
    assert "sessionid" not in resp.cookies


def test_rol_servicio_no_se_combina_con_roles_humanos(crear_usuario):
    usuario = crear_usuario(
        username="integracion_rrhh",
        password="clave-segura-123",
        rol=roles.SERVICIO,
    )
    grupo_rrhh, _ = Group.objects.get_or_create(name=roles.RRHH)

    with pytest.raises(ValidationError, match="exclusivo"):
        with transaction.atomic():
            usuario.groups.add(grupo_rrhh)

    assert set(usuario.roles) == {roles.SERVICIO}


def test_sesion_previa_se_revoca_si_aparece_servicio_en_datos_heredados(
    api_client,
    crear_usuario,
):
    """La autenticación falla cerrada incluso si se saltearon las señales del dominio."""

    usuario = crear_usuario(
        username="rrhh_previo",
        password="clave-segura-123",
        rol=roles.RRHH,
    )
    assert api_client.post(
        "/api/v1/auth/login/",
        {"username": "rrhh_previo", "password": "clave-segura-123"},
        format="json",
    ).status_code == 200
    servicio, _ = Group.objects.get_or_create(name=roles.SERVICIO)
    # Simula una fila legada o una carga SQL externa: el contrato por request no depende
    # de que todas las escrituras históricas hayan pasado por m2m_changed.
    usuario.groups.through.objects.create(usuario=usuario, group=servicio)

    respuesta = api_client.get("/api/v1/mi/perfil/")

    assert respuesta.status_code == 401
    assert respuesta.data["codigo"] == "authentication_failed"


def test_superusuario_sin_grupo_servicio_puede_abrir_sesion(
    api_client, crear_usuario
):
    usuario = crear_usuario(
        username="administrador",
        password="clave-segura-123",
    )
    usuario.is_staff = True
    usuario.is_superuser = True
    usuario.save(update_fields=["is_staff", "is_superuser"])

    resp = api_client.post(
        "/api/v1/auth/login/",
        {"username": "administrador", "password": "clave-segura-123"},
        format="json",
    )

    assert resp.status_code == 200
    assert "sessionid" in resp.cookies


def test_logout_invalida_la_sesion(api_client, crear_usuario):
    crear_usuario(username="luciana", password="clave-segura-123")
    api_client.post(
        "/api/v1/auth/login/",
        {"username": "luciana", "password": "clave-segura-123"},
        format="json",
    )

    assert api_client.post("/api/v1/auth/logout/").status_code == 204
    assert api_client.get("/api/v1/mi/perfil/").status_code in (401, 403)


def test_si_falla_la_auditoria_el_logout_no_invalida_la_sesion(
    api_client, crear_usuario, monkeypatch
):
    crear_usuario(username="luciana", password="clave-segura-123")
    api_client.post(
        "/api/v1/auth/login/",
        {"username": "luciana", "password": "clave-segura-123"},
        format="json",
    )

    def fallar_auditoria(**_kwargs):
        raise RuntimeError("auditoría no disponible")

    monkeypatch.setattr(
        "apps.usuarios.api.views.registrar_evento",
        fallar_auditoria,
    )
    api_client.raise_request_exception = False

    assert api_client.post("/api/v1/auth/logout/").status_code == 500
    assert api_client.get("/api/v1/mi/perfil/").status_code == 200


def test_endpoint_csrf_entrega_cookie(api_client):
    resp = api_client.get("/api/v1/auth/csrf/")
    assert resp.status_code == 200
    assert "csrftoken" in resp.cookies


def test_login_y_logout_exigen_csrf_real(crear_usuario):
    crear_usuario(username="luciana", password="clave-segura-123")
    cliente = APIClient(enforce_csrf_checks=True)
    credenciales = {"username": "luciana", "password": "clave-segura-123"}

    assert cliente.post("/api/v1/auth/login/", credenciales, format="json").status_code == 403

    csrf = cliente.get("/api/v1/auth/csrf/").cookies["csrftoken"].value
    login = cliente.post(
        "/api/v1/auth/login/",
        credenciales,
        format="json",
        HTTP_X_CSRFTOKEN=csrf,
    )
    assert login.status_code == 200

    assert cliente.post("/api/v1/auth/logout/").status_code == 403
    csrf_rotado = cliente.cookies["csrftoken"].value
    assert (
        cliente.post("/api/v1/auth/logout/", HTTP_X_CSRFTOKEN=csrf_rotado).status_code
        == 204
    )


def test_mi_perfil_devuelve_roles(cliente_rrhh):
    resp = cliente_rrhh.get("/api/v1/mi/perfil/")
    assert resp.status_code == 200
    assert resp.data["username"] == "rrhh"
    assert "RRHH" in resp.data["roles"]


def test_mi_perfil_requiere_auth(api_client):
    resp = api_client.get("/api/v1/mi/perfil/")
    assert resp.status_code == 401


def test_la_api_no_se_guarda_en_caches_compartidos(cliente_rrhh):
    resp = cliente_rrhh.get("/api/v1/mi/perfil/")

    assert resp.headers["Cache-Control"] == "no-store, private"
    assert resp.headers["Pragma"] == "no-cache"
