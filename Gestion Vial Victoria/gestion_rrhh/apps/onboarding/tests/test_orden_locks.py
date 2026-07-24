from datetime import date

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.empleados.models import Empleado, RelacionLaboral
from apps.onboarding.models import ProcesoEmpleado, TipoProceso
from apps.onboarding.services import iniciar_proceso
from apps.organizacion.models import Empresa, Puesto, Sector
from common import roles

pytestmark = pytest.mark.django_db


def test_iniciar_proceso_bloquea_empleado_antes_que_relacion(crear_usuario):
    actor = crear_usuario(username="rrhh-locks", rol=roles.RRHH)
    empresa = Empresa.objects.create(nombre="Empresa locks")
    sector = Sector.objects.create(nombre="Operaciones locks")
    puesto = Puesto.objects.create(nombre="Chofer locks", sector=sector)
    empleado = Empleado.objects.create(
        legajo="LOCK-001",
        dni="40987654",
        nombre="Juan",
        apellido="Locks",
    )
    relacion = RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=empresa,
        sector=sector,
        puesto=puesto,
        fecha_ingreso=date(2025, 1, 1),
    )

    with CaptureQueriesContext(connection) as consultas:
        proceso = iniciar_proceso(
            actor=actor,
            relacion=relacion,
            tipo_proceso=TipoProceso.INGRESO,
        )

    bloqueos = [
        consulta["sql"]
        for consulta in consultas.captured_queries
        if "FOR UPDATE" in consulta["sql"].upper()
    ]
    assert len(bloqueos) >= 2
    assert 'FROM "empleados_empleado"' in bloqueos[0]
    assert 'FROM "empleados_relacionlaboral"' in bloqueos[1]
    assert ProcesoEmpleado.objects.filter(pk=proceso.pk).exists()
