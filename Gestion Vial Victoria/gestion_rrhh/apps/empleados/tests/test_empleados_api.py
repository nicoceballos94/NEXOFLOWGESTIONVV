"""Tests de la app empleados: alta con relación, R1, baja lógica (R10), scoping y documentos."""
import pytest

from apps.empleados.models import Empleado, EstadoRelacion, RelacionLaboral
from apps.organizacion.models import Empresa

pytestmark = pytest.mark.django_db


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="VIAL VICTORIA")


def _payload_alta(empresa, **over):
    # Sin `legajo`: lo asigna el backend (ver test_el_legajo_lo_asigna_el_backend).
    datos = {
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
        "dni": "30999888",
        "nombre": "Ana",
        "apellido": "Gómez",
        "relacion": {"empresa": 999999, "fecha_ingreso": "2024-01-10"},
    }
    resp = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")
    assert resp.status_code == 400
    assert not Empleado.objects.filter(dni="30999888").exists()


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
        _payload_alta(empresa, dni="30222333"),  # el backend le da el "0002"
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


# ---------- Filtros ----------
def test_filtro_empresa_y_estado_miran_la_misma_relacion(cliente_rrhh, empresa):
    """B1: con los filtros en .filter() separados, cada uno generaba su propio JOIN y podían
    satisfacerse con relaciones DISTINTAS: quien se fue de la empresa B y hoy está activo en
    la A aparecía como "activo de la empresa B"."""
    otra = Empresa.objects.create(nombre="VICTORIA SUR")
    empleado = Empleado.objects.create(
        legajo="0100", dni="30777888", nombre="Mudó", apellido="DeEmpresa"
    )
    RelacionLaboral.objects.create(  # finalizada en `otra`
        empleado=empleado, empresa=otra, fecha_ingreso="2020-01-01",
        fecha_egreso="2023-12-31", estado=EstadoRelacion.FINALIZADA,
    )
    RelacionLaboral.objects.create(  # activa en `empresa`
        empleado=empleado, empresa=empresa, fecha_ingreso="2024-01-01",
        estado=EstadoRelacion.ACTIVA,
    )

    # No es un activo de `otra`: ahí está finalizado.
    resp = cliente_rrhh.get(f"/api/v1/empleados/?empresa={otra.id}&estado=ACTIVA")
    assert resp.data["count"] == 0, resp.data

    # Sí es un activo de `empresa`.
    resp = cliente_rrhh.get(f"/api/v1/empleados/?empresa={empresa.id}&estado=ACTIVA")
    assert [e["id"] for e in resp.data["results"]] == [empleado.id]

    # Y sigue siendo un finalizado de `otra`.
    resp = cliente_rrhh.get(f"/api/v1/empleados/?empresa={otra.id}&estado=FINALIZADA")
    assert [e["id"] for e in resp.data["results"]] == [empleado.id]


# ---------- Documentos ----------
def test_documento_se_corrige_y_se_elimina(cliente_rrhh, empresa):
    """B4: con solo GET/POST y el UNIQUE (empleado, tipo), un documento mal cargado era un
    callejón sin salida: no se podía ni corregir el vencimiento ni recargarlo."""
    from apps.empleados.models import TipoDocumento

    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(dni="30111222")
    tipo = TipoDocumento.objects.create(nombre="Apto médico")

    creado = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id, "numero": "AM-1", "fecha_vencimiento": "2026-01-01"},
        format="json",
    )
    assert creado.status_code == 201, creado.data
    doc_id = creado.data["id"]

    # Renovar = mover el vencimiento.
    resp = cliente_rrhh.patch(
        f"/api/v1/empleados/{empleado.id}/documentos/{doc_id}/",
        {"fecha_vencimiento": "2027-01-01"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["fecha_vencimiento"] == "2027-01-01"

    # Eliminar libera el UNIQUE para volver a cargarlo.
    resp = cliente_rrhh.delete(f"/api/v1/empleados/{empleado.id}/documentos/{doc_id}/")
    assert resp.status_code == 204
    resp = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id, "numero": "AM-2"},
        format="json",
    )
    assert resp.status_code == 201, resp.data


def test_empleado_no_puede_editar_documentos(cliente_rrhh, empresa, crear_usuario):
    from rest_framework.test import APIClient

    from apps.empleados.models import TipoDocumento
    from common import roles

    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(dni="30111222")
    tipo = TipoDocumento.objects.create(nombre="Apto médico")
    doc_id = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id, "numero": "AM-1"},
        format="json",
    ).data["id"]
    # Cliente propio: los `cliente_*` del conftest comparten una única instancia de
    # APIClient, así que pedir dos roles en el mismo test haría que el segundo pise al primero.
    cliente_empleado = APIClient()
    cliente_empleado.force_authenticate(crear_usuario(username="pepe", rol=roles.EMPLEADO))
    resp = cliente_empleado.patch(
        f"/api/v1/empleados/{empleado.id}/documentos/{doc_id}/",
        {"numero": "HACKEADO"},
        format="json",
    )
    assert resp.status_code == 403


# ---------- Legajo (lo asigna el backend, no el cliente) ----------
def test_el_legajo_lo_asigna_el_backend_ignorando_al_cliente(cliente_rrhh, empresa):
    """Antes lo calculaba el navegador con max+1 sobre lo que tenía cargado: dos altas
    simultáneas generaban el mismo número. Ahora el cliente no opina."""
    resp = cliente_rrhh.post(
        "/api/v1/empleados/", _payload_alta(empresa, legajo="9999"), format="json"
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["legajo"] == "0001"  # el "9999" del cliente se ignora


def test_los_legajos_siguen_la_serie(cliente_rrhh, empresa):
    primero = cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    segundo = cliente_rrhh.post(
        "/api/v1/empleados/", _payload_alta(empresa, dni="30333444"), format="json"
    )
    assert primero.data["legajo"] == "0001"
    assert segundo.data["legajo"] == "0002"


def test_la_serie_ignora_los_legajos_no_numericos(cliente_rrhh, empresa):
    """Un legajo importado con formato propio no rompe ni secuestra la numeración."""
    Empleado.objects.create(legajo="IMPORT-A", dni="20000001", nombre="Vieja", apellido="Data")
    resp = cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    assert resp.status_code == 201, resp.data
    assert resp.data["legajo"] == "0001"
