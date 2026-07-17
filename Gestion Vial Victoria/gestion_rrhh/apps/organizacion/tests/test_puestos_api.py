"""Catálogo de puestos: unicidad case-insensitive (D6).

El puesto se escribe a mano en el alta de empleados, así que el catálogo se ensucia con
variantes del mismo puesto ("Chofer" / "chofer" / "CHOFER ") que después parten los
filtros en dos. El backend colapsa esas variantes en una sola fila.
"""
import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.organizacion.models import Puesto
from common import roles

pytestmark = pytest.mark.django_db

URL = "/api/v1/puestos/"


@pytest.fixture
def cliente_rrhh(crear_usuario):
    cliente = APIClient()
    cliente.force_authenticate(crear_usuario(username="rrhh", rol=roles.RRHH))
    return cliente


def test_post_de_variante_devuelve_el_existente(cliente_rrhh):
    """El caso del análisis: 'chofer' no debe crear un segundo puesto junto a 'Chofer'."""
    original = Puesto.objects.create(nombre="Chofer")
    resp = cliente_rrhh.post(URL, {"nombre": "chofer"}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["id"] == original.id
    assert Puesto.objects.count() == 1


def test_post_con_espacios_sobrantes_devuelve_el_existente(cliente_rrhh):
    original = Puesto.objects.create(nombre="Chofer")
    resp = cliente_rrhh.post(URL, {"nombre": "  CHOFER  "}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["id"] == original.id
    assert Puesto.objects.count() == 1


def test_post_de_puesto_nuevo_sigue_creando(cliente_rrhh):
    """La idempotencia no debe tapar el alta legítima de un puesto que no existía."""
    resp = cliente_rrhh.post(URL, {"nombre": "Soldador"}, format="json")
    assert resp.status_code == 201, resp.data
    assert Puesto.objects.filter(nombre="Soldador").count() == 1


def test_nombre_se_guarda_sin_espacios_sobrantes(cliente_rrhh):
    resp = cliente_rrhh.post(URL, {"nombre": "  Soldador  "}, format="json")
    assert resp.status_code == 201, resp.data
    assert Puesto.objects.get(id=resp.data["id"]).nombre == "Soldador"


def test_la_base_rechaza_el_duplicado_ci(cliente_rrhh):
    """La garantía no vive solo en la vista: el constraint la sostiene para cualquier cliente."""
    Puesto.objects.create(nombre="Chofer")
    with pytest.raises(IntegrityError):
        Puesto.objects.create(nombre="chofer")
