import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from common import roles

pytestmark = pytest.mark.django_db


def _cliente(usuario):
    cliente = APIClient()
    cliente.force_authenticate(usuario)
    return cliente


def test_rrhh_lista_solo_supervisores_humanos_activos_con_salida_minima(
    cliente_rrhh, crear_usuario
):
    valido = crear_usuario(
        username="supervisor-activo",
        rol=roles.SUPERVISOR,
        first_name="Ana",
        last_name="Pérez",
        email="ana@example.com",
    )
    crear_usuario(
        username="supervisor-inactivo",
        rol=roles.SUPERVISOR,
        is_active=False,
    )
    crear_usuario(username="solo-rrhh", rol=roles.RRHH)
    mixto = crear_usuario(username="robot-supervisor", rol=roles.SUPERVISOR)
    servicio = Group.objects.get_or_create(name=roles.SERVICIO)[0]
    # Dato legado que salteó la regla de exclusividad: el selector igualmente falla cerrado.
    mixto.groups.through.objects.create(usuario=mixto, group=servicio)

    resp = cliente_rrhh.get("/api/v1/supervisores/?activo=true")

    assert resp.status_code == 200, resp.data
    assert resp.data == [
        {
            "id": valido.id,
            "username": "supervisor-activo",
            "nombre_completo": "Ana Pérez",
        }
    ]
    assert "email" not in resp.data[0]


def test_catalogo_puede_consultar_inactivos_y_usa_username_si_no_hay_nombre(
    cliente_rrhh, crear_usuario
):
    inactivo = crear_usuario(
        username="supervisor-inactivo",
        rol=roles.SUPERVISOR,
        is_active=False,
    )
    crear_usuario(username="supervisor-activo", rol=roles.SUPERVISOR)

    resp = cliente_rrhh.get("/api/v1/supervisores/?activo=false")

    assert resp.status_code == 200, resp.data
    assert resp.data == [
        {
            "id": inactivo.id,
            "username": "supervisor-inactivo",
            "nombre_completo": "supervisor-inactivo",
        }
    ]


def test_catalogo_rechaza_filtro_activo_invalido(cliente_rrhh):
    resp = cliente_rrhh.get("/api/v1/supervisores/?activo=quizas")

    assert resp.status_code == 400
    assert "activo" in resp.data["campos"]


def test_catalogo_de_supervisores_es_solo_para_rrhh_o_admin(
    crear_usuario, cliente_empleado
):
    admin = crear_usuario(username="admin-catalogo", rol=roles.ADMIN)

    assert _cliente(admin).get("/api/v1/supervisores/").status_code == 200
    assert cliente_empleado.get("/api/v1/supervisores/").status_code == 403
    assert APIClient().get("/api/v1/supervisores/").status_code == 401
