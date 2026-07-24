from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.empleados.management.commands.seed_datos_prueba import Command
from apps.empleados.models import Empleado
from apps.organizacion.models import Puesto, Sector

pytestmark = pytest.mark.django_db


def test_seed_funciona_en_base_nueva_con_actor_tecnico_deshabilitado():
    salida = StringIO()

    call_command("seed_datos_prueba", empleados=1, stdout=salida)

    actor = get_user_model().objects.get(username="__seed_datos_prueba__")
    assert actor.is_active is False
    assert actor.has_usable_password() is False
    assert Empleado.objects.count() == 1
    relacion = Empleado.objects.get().relacion_activa
    assert relacion.puesto.sector_id == relacion.sector_id


def test_seed_no_ofrece_reset_fisico_de_datos_auditados():
    with pytest.raises(CommandError, match="No se permite borrar físicamente"):
        call_command("seed_datos_prueba", reset=True)

    assert Empleado.objects.count() == 0


def test_puesto_demo_se_resuelve_dentro_de_cada_sector():
    sector_uno = Sector.objects.create(nombre="Logística")
    sector_dos = Sector.objects.create(nombre="Operaciones")
    comando = Command()

    puesto_uno = comando._puesto("Chofer", sector_uno)
    puesto_dos = comando._puesto("chofer", sector_dos)

    assert puesto_uno.pk != puesto_dos.pk
    assert Puesto.objects.filter(nombre__iexact="chofer").count() == 2
