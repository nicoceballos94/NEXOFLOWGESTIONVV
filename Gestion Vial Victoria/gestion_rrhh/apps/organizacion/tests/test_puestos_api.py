"""Puestos: catálogo sectorizado, sin altas implícitas ni duplicados por mayúsculas."""

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.organizacion.models import Puesto, Sector
from common import roles

pytestmark = pytest.mark.django_db

URL = "/api/v1/puestos/"


@pytest.fixture
def cliente_rrhh(crear_usuario):
    cliente = APIClient()
    cliente.force_authenticate(crear_usuario(username="rrhh", rol=roles.RRHH))
    return cliente


@pytest.fixture
def sectores():
    return (
        Sector.objects.create(nombre="Operaciones"),
        Sector.objects.create(nombre="Taller"),
    )


def test_puesto_nuevo_requiere_sector_y_normaliza_nombre(cliente_rrhh, sectores):
    operaciones, _ = sectores
    sin_sector = cliente_rrhh.post(URL, {"nombre": "Chofer"}, format="json")
    assert sin_sector.status_code == 400
    assert "sector" in str(sin_sector.data)

    creado = cliente_rrhh.post(
        URL,
        {"nombre": "  Chofer  ", "sector": operaciones.id},
        format="json",
    )
    assert creado.status_code == 201, creado.data
    puesto = Puesto.objects.get(pk=creado.data["id"])
    assert puesto.nombre == "Chofer"
    assert puesto.sector == operaciones


def test_duplicado_ci_se_rechaza_dentro_del_mismo_sector(cliente_rrhh, sectores):
    operaciones, _ = sectores
    original = Puesto.objects.create(nombre="Chofer", sector=operaciones)

    respuesta = cliente_rrhh.post(
        URL,
        {"nombre": "  CHOFER  ", "sector": operaciones.id},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "nombre" in str(respuesta.data)
    assert Puesto.objects.filter(sector=operaciones).count() == 1
    assert Puesto.objects.get(sector=operaciones) == original


def test_mismo_nombre_es_valido_en_sectores_distintos(cliente_rrhh, sectores):
    operaciones, taller = sectores

    primero = cliente_rrhh.post(
        URL, {"nombre": "Encargado", "sector": operaciones.id}, format="json"
    )
    segundo = cliente_rrhh.post(
        URL, {"nombre": "encargado", "sector": taller.id}, format="json"
    )

    assert primero.status_code == 201, primero.data
    assert segundo.status_code == 201, segundo.data
    assert Puesto.objects.filter(nombre__iexact="encargado").count() == 2


def test_api_no_admite_sector_inactivo(cliente_rrhh):
    sector = Sector.objects.create(nombre="Legado", activo=False)

    respuesta = cliente_rrhh.post(
        URL, {"nombre": "Puesto viejo", "sector": sector.id}, format="json"
    )

    assert respuesta.status_code == 400
    assert "sector" in str(respuesta.data)


def test_la_base_exige_sector_para_nuevos_puestos():
    with pytest.raises(IntegrityError), transaction.atomic():
        Puesto.objects.create(nombre="Huérfano")


def test_la_base_rechaza_duplicado_ci_solo_en_el_mismo_sector(sectores):
    operaciones, taller = sectores
    Puesto.objects.create(nombre="Chofer", sector=operaciones)

    with pytest.raises(IntegrityError), transaction.atomic():
        Puesto.objects.create(nombre="chofer", sector=operaciones)

    Puesto.objects.create(nombre="chofer", sector=taller)
