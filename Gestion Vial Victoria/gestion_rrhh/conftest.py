"""Fixtures compartidas de pytest."""
import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from common import roles


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def crear_usuario(db, django_user_model):
    """Factory simple de usuarios con rol. factory_boy entra en MVP1 con empleados."""

    def _crear(username="usuario", rol=None, password="clave-segura-123", **extra):
        usuario = django_user_model.objects.create_user(
            username=username, password=password, **extra
        )
        if rol:
            grupo, _ = Group.objects.get_or_create(name=rol)
            usuario.groups.add(grupo)
        return usuario

    return _crear


@pytest.fixture
def cliente_rrhh(api_client, crear_usuario):
    usuario = crear_usuario(username="rrhh", rol=roles.RRHH)
    api_client.force_authenticate(usuario)
    return api_client


@pytest.fixture
def cliente_empleado(api_client, crear_usuario):
    usuario = crear_usuario(username="empleado", rol=roles.EMPLEADO)
    api_client.force_authenticate(usuario)
    return api_client
