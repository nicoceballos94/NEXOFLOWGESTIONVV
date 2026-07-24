"""Fixtures compartidas de pytest."""
import pytest
from django.contrib.auth.models import Group
from django.db import connections
from rest_framework.test import APIClient

from common import roles


@pytest.fixture(scope="session", autouse=True)
def permitir_solo_el_flush_de_teardown_de_pytest():
    """Mantiene append-only durante el test, pero deja limpiar la DB entre tests reales.

    Los tests ``transaction=True`` se limpian con ``flush`` en su teardown. Django ejecuta
    ese flush mediante ``execute_sql_flush`` y el trigger productivo, correctamente,
    bloquea el TRUNCATE de la bitácora. Se envuelve únicamente ese método interno del
    runner: un TRUNCATE/UPDATE/DELETE ejecutado por el código bajo prueba sigue llegando al
    trigger habilitado y falla igual que en producción.

    El trigger se vuelve a habilitar en ``finally`` antes de que arranque el test siguiente,
    aun si el flush falla. No se cambia ninguna migración ni configuración productiva.
    """
    connection = connections["default"]
    ejecutar_flush = connection.ops.execute_sql_flush

    def ejecutar_flush_de_test(sql_list):
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE auditoria_registroauditoria "
                "DISABLE TRIGGER auditoria_append_only_truncate"
            )
        try:
            return ejecutar_flush(sql_list)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE auditoria_registroauditoria "
                    "ENABLE TRIGGER auditoria_append_only_truncate"
                )

    connection.ops.execute_sql_flush = ejecutar_flush_de_test
    try:
        yield
    finally:
        connection.ops.execute_sql_flush = ejecutar_flush


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
