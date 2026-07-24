import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.empleados.models import Empleado, RelacionLaboral
from apps.organizacion.models import Empresa, Puesto, Sector
from common import roles

pytestmark = pytest.mark.django_db


def _asignar_equipo(supervisor):
    empresa = Empresa.objects.create(nombre="VIAL VICTORIA")
    sector = Sector.objects.create(nombre="Operaciones")
    puesto = Puesto.objects.create(nombre="Chofer", sector=sector)
    empleado = Empleado.objects.create(
        legajo="0001",
        dni="30111222",
        nombre="Juan",
        apellido="Pérez",
    )
    return RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=empresa,
        sector=sector,
        puesto=puesto,
        supervisor=supervisor,
        fecha_ingreso="2024-01-10",
    )


def test_no_desactiva_usuario_con_equipo_activo(crear_usuario):
    supervisor = crear_usuario(username="super-activo", rol=roles.SUPERVISOR)
    _asignar_equipo(supervisor)
    supervisor.is_active = False

    with pytest.raises(ValidationError, match="Reasigná"):
        supervisor.save(update_fields=["is_active"])

    supervisor.refresh_from_db()
    assert supervisor.is_active is True


def test_no_quita_rol_ni_agrega_servicio_a_supervisor_con_equipo(
    crear_usuario,
):
    supervisor = crear_usuario(username="super-roles", rol=roles.SUPERVISOR)
    _asignar_equipo(supervisor)
    grupo_supervisor = Group.objects.get(name=roles.SUPERVISOR)
    grupo_servicio = Group.objects.get_or_create(name=roles.SERVICIO)[0]

    with pytest.raises(ValidationError, match="conservar"):
        with transaction.atomic():
            supervisor.groups.remove(grupo_supervisor)
    with pytest.raises(ValidationError, match="exclusivo|conservar"):
        with transaction.atomic():
            supervisor.groups.add(grupo_servicio)

    assert supervisor.groups.filter(name=roles.SUPERVISOR).exists()
    assert not supervisor.groups.filter(name=roles.SERVICIO).exists()
