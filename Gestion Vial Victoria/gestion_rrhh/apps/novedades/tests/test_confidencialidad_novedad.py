from datetime import date

import pytest

from apps.empleados.models import Empleado, RelacionLaboral
from apps.novedades.confidencialidad import CAMPOS_CONFIDENCIALES_NOVEDAD
from apps.novedades.models import ClasificacionNovedad, Novedad, TipoNovedad
from apps.organizacion.models import Empresa, Puesto, Sector
from common import roles

pytestmark = pytest.mark.django_db


def test_supervisor_no_recibe_campos_confidenciales_y_rrhh_si(
    api_client,
    crear_usuario,
):
    supervisor = crear_usuario(username="super-confidencial", rol=roles.SUPERVISOR)
    rrhh = crear_usuario(username="rrhh-confidencial", rol=roles.RRHH)
    empresa = Empresa.objects.create(nombre="Empresa confidencial")
    sector = Sector.objects.create(nombre="Operaciones confidencial")
    puesto = Puesto.objects.create(nombre="Chofer confidencial", sector=sector)
    empleado = Empleado.objects.create(
        legajo="CONF-001",
        dni="40123456",
        nombre="Ana",
        apellido="Privada",
    )
    relacion = RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=empresa,
        sector=sector,
        puesto=puesto,
        supervisor=supervisor,
        fecha_ingreso=date(2025, 1, 1),
    )
    tipo = TipoNovedad.objects.create(
        codigo="LICENCIA_CONFIDENCIAL",
        nombre="Licencia confidencial",
        ocupa_periodo=True,
        requiere_certificado=True,
    )
    novedad = Novedad.objects.create(
        empleado=empleado,
        relacion_laboral=relacion,
        tipo_novedad=tipo,
        fecha_desde=date(2025, 3, 1),
        fecha_hasta=date(2025, 3, 10),
        clasificacion=ClasificacionNovedad.JUSTIFICADA,
        motivo="Diagnóstico reservado",
        observaciones="Tratamiento reservado",
        requiere_praxis=True,
        fecha_turno_praxis=date(2025, 3, 4),
        certificado_recibido_en=date(2025, 3, 2),
    )
    url = f"/api/v1/novedades/{novedad.pk}/"

    api_client.force_authenticate(supervisor)
    respuesta_supervisor = api_client.get(url)

    assert respuesta_supervisor.status_code == 200
    assert CAMPOS_CONFIDENCIALES_NOVEDAD.isdisjoint(respuesta_supervisor.data)
    assert respuesta_supervisor.data["fecha_desde"] == "2025-03-01"
    assert respuesta_supervisor.data["estado"] == "REGISTRADA"

    api_client.force_authenticate(rrhh)
    respuesta_rrhh = api_client.get(url)

    assert respuesta_rrhh.status_code == 200
    assert CAMPOS_CONFIDENCIALES_NOVEDAD.issubset(respuesta_rrhh.data)
    assert respuesta_rrhh.data["clasificacion"] == ClasificacionNovedad.JUSTIFICADA
    assert respuesta_rrhh.data["requiere_praxis"] is True
    assert respuesta_rrhh.data["fecha_turno_praxis"] == "2025-03-04"
