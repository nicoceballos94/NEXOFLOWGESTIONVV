import pytest
from django.db import DatabaseError
from django.test import override_settings

pytestmark = pytest.mark.django_db


def test_healthcheck_es_publico_y_minimo(client):
    respuesta = client.get("/healthz/")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}
    assert respuesta.headers["Cache-Control"] == (
        "max-age=0, no-cache, no-store, must-revalidate, private"
    )


def test_healthcheck_solo_acepta_get(client):
    assert client.post("/healthz/").status_code == 405


def test_healthcheck_devuelve_503_sin_filtrar_el_error_de_base(client, monkeypatch):
    def base_no_disponible():
        raise DatabaseError("host interno y credenciales que no deben salir")

    monkeypatch.setattr("config.views.connection.cursor", base_no_disponible)

    respuesta = client.get("/healthz/")

    assert respuesta.status_code == 503
    assert respuesta.json() == {"status": "unavailable"}
    assert b"host interno" not in respuesta.content


@override_settings(
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
def test_healthcheck_interno_respeta_proto_del_proxy(client):
    respuesta = client.get("/healthz/", HTTP_X_FORWARDED_PROTO="https")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}
