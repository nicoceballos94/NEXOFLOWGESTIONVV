"""Tests de la app empleados: alta con relación, R1, baja lógica (R10), scoping y documentos."""
import pytest

from apps.empleados.models import Empleado, EstadoRelacion, RelacionLaboral
from apps.organizacion.models import Empresa

pytestmark = pytest.mark.django_db


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="VIAL VICTORIA")


def _payload_alta(empresa, **over):
    datos = {
        "legajo": "0001",
        "dni": "30111222",
        "nombre": "Juan",
        "apellido": "Pérez",
        "relacion": {"empresa": empresa.id, "fecha_ingreso": "2024-01-10"},
    }
    datos.update(over)
    return datos


def test_rrhh_da_alta_empleado_con_relacion_activa(cliente_rrhh, empresa):
    resp = cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    assert resp.status_code == 201, resp.data
    empleado = Empleado.objects.get(legajo="0001")
    assert empleado.relaciones.filter(estado=EstadoRelacion.ACTIVA).count() == 1
    assert resp.data["activo"] is True


def test_alta_es_atomica_si_falla_la_relacion(cliente_rrhh):
    # empresa inexistente -> falla la relación -> no debe quedar el empleado (transacción).
    payload = {
        "legajo": "0009",
        "dni": "30999888",
        "nombre": "Ana",
        "apellido": "Gómez",
        "relacion": {"empresa": 999999, "fecha_ingreso": "2024-01-10"},
    }
    resp = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")
    assert resp.status_code == 400
    assert not Empleado.objects.filter(legajo="0009").exists()


def test_no_dos_relaciones_activas_misma_empresa(cliente_rrhh, empresa):
    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(legajo="0001")
    # intentar una segunda relación ACTIVA en la misma empresa (R1)
    from apps.empleados import services

    with pytest.raises(Exception):
        services.crear_relacion_laboral(
            actor=None, empleado=empleado, empresa=empresa, fecha_ingreso="2024-05-01"
        )
    assert empleado.relaciones.filter(estado=EstadoRelacion.ACTIVA).count() == 1


def test_empleado_no_puede_dar_alta(cliente_empleado, empresa):
    resp = cliente_empleado.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    assert resp.status_code == 403


def test_baja_logica_finaliza_relacion_sin_borrar(cliente_rrhh, empresa):
    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(legajo="0001")
    relacion = empleado.relacion_activa
    url = f"/api/v1/empleados/{empleado.id}/relaciones/{relacion.id}/finalizar/"
    resp = cliente_rrhh.post(
        url, {"fecha_egreso": "2025-03-01", "motivo_egreso": "RENUNCIA"}, format="json"
    )
    assert resp.status_code == 200, resp.data
    relacion.refresh_from_db()
    assert relacion.estado == EstadoRelacion.FINALIZADA
    assert relacion.fecha_egreso.isoformat() == "2025-03-01"
    assert RelacionLaboral.objects.filter(pk=relacion.pk).exists()  # no se borró (R10)


def test_reingreso_crea_nueva_relacion_activa(cliente_rrhh, empresa):
    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(legajo="0001")
    relacion = empleado.relacion_activa
    # baja
    cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/relaciones/{relacion.id}/finalizar/",
        {"fecha_egreso": "2025-03-01", "motivo_egreso": "RENUNCIA"},
        format="json",
    )
    # reingreso: nueva relación ACTIVA
    resp = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/relaciones/",
        {"empresa": empresa.id, "fecha_ingreso": "2025-06-01"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert empleado.relaciones.filter(estado=EstadoRelacion.ACTIVA).count() == 1
    assert empleado.relaciones.count() == 2


def test_no_hay_delete_de_empleados(cliente_rrhh, empresa):
    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(legajo="0001")
    resp = cliente_rrhh.delete(f"/api/v1/empleados/{empleado.id}/")
    assert resp.status_code == 405  # baja = finalizar relación, nunca DELETE físico


def test_empleado_solo_ve_su_propia_ficha(cliente_rrhh, empresa, crear_usuario, api_client):
    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa, legajo="0002", dni="30222333"),
        format="json",
    )
    # un usuario Empleado vinculado a la primera ficha solo debe verse a sí mismo
    from common import roles

    usuario = crear_usuario(username="juanp", rol=roles.EMPLEADO)
    empleado = Empleado.objects.get(legajo="0001")
    empleado.usuario = usuario
    empleado.save()
    api_client.force_authenticate(usuario)
    resp = api_client.get("/api/v1/empleados/")
    assert resp.status_code == 200
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["legajo"] == "0001"


def test_legajo_duplicado_error_uniforme(cliente_rrhh, empresa):
    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    resp = cliente_rrhh.post(
        "/api/v1/empleados/", _payload_alta(empresa, dni="30333444"), format="json"
    )
    assert resp.status_code == 400
    assert resp.data["codigo"] == "validacion"
    assert "legajo" in resp.data["campos"]
