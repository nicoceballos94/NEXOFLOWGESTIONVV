"""Tests de la app novedades: alta, permisos, transiciones y cadena de prórrogas (§6 bis).

Cubre las reglas críticas del MVP1: R11 (solo RRHH aprueba), RP2/RP3/RP4/RP5/RP7 de la
cadena, RP6 (no anular la madre con prórrogas activas) y la vigencia efectiva calculada.
"""
import pytest
from rest_framework.test import APIClient

from apps.empleados.models import Empleado, RelacionLaboral
from apps.novedades.models import EstadoNovedad, Novedad, TipoNovedad
from apps.organizacion.models import Empresa
from common import roles

pytestmark = pytest.mark.django_db


# Clientes independientes por rol: a diferencia de los de conftest (que comparten una
# única instancia de APIClient), estos permiten usar dos roles en el mismo test —
# p. ej. el Supervisor carga y RRHH aprueba— sin que un force_authenticate pise al otro.
def _cliente(crear_usuario, *, rol, username):
    cliente = APIClient()
    cliente.force_authenticate(crear_usuario(username=username, rol=rol))
    return cliente


@pytest.fixture
def cliente_rrhh(crear_usuario):
    return _cliente(crear_usuario, rol=roles.RRHH, username="rrhh")


@pytest.fixture
def cliente_empleado(crear_usuario):
    return _cliente(crear_usuario, rol=roles.EMPLEADO, username="empleado")


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="VIAL VICTORIA")


@pytest.fixture
def empleado(empresa):
    emp = Empleado.objects.create(legajo="0001", dni="30111222", nombre="Juan", apellido="Pérez")
    RelacionLaboral.objects.create(empleado=emp, empresa=empresa, fecha_ingreso="2024-01-10")
    return emp


@pytest.fixture
def tipo_licencia():
    return TipoNovedad.objects.create(
        codigo="LICENCIA_MEDICA",
        nombre="Licencia médica",
        justifica_ausencia=True,
        requiere_certificado=True,
        admite_prorroga=True,
    )


@pytest.fixture
def tipo_horas_extra():
    return TipoNovedad.objects.create(
        codigo="HORAS_EXTRA", nombre="Horas extra", requiere_cantidad_horas=True
    )


@pytest.fixture
def cliente_supervisor(crear_usuario):
    return _cliente(crear_usuario, rol=roles.SUPERVISOR, username="super")


def _alta(cliente, empleado, tipo, **over):
    payload = {
        "empleado": empleado.id,
        "tipo_novedad": tipo.id,
        "fecha_desde": "2025-03-01",
        "fecha_hasta": "2025-03-10",
        "motivo": "Pie roto",
    }
    payload.update(over)
    return cliente.post("/api/v1/novedades/", payload, format="json")


# ---------- Alta y validaciones ----------
def test_supervisor_carga_novedad_registrada(cliente_supervisor, empleado, tipo_licencia):
    resp = _alta(cliente_supervisor, empleado, tipo_licencia)
    assert resp.status_code == 201, resp.data
    assert resp.data["estado"] == EstadoNovedad.REGISTRADA
    novedad = Novedad.objects.get(pk=resp.data["id"])
    # la relación activa se toma por defecto
    assert novedad.relacion_laboral == empleado.relacion_activa


def test_alta_por_dias_calcula_fecha_hasta(cliente_supervisor, empleado, tipo_licencia):
    resp = _alta(cliente_supervisor, empleado, tipo_licencia, fecha_hasta=None, dias=5)
    assert resp.status_code == 201, resp.data
    assert resp.data["fecha_hasta"] == "2025-03-05"  # desde + (5-1) días


def test_horas_extra_exige_cantidad(cliente_supervisor, empleado, tipo_horas_extra):
    resp = _alta(cliente_supervisor, empleado, tipo_horas_extra, fecha_hasta=None)
    assert resp.status_code == 400
    assert "cantidad_horas" in resp.data["campos"]


def test_empleado_no_puede_cargar_novedad(cliente_empleado, empleado, tipo_licencia):
    resp = _alta(cliente_empleado, empleado, tipo_licencia)
    assert resp.status_code == 403


# ---------- Transiciones ----------
def test_supervisor_no_aprueba_solo_rrhh(cliente_supervisor, empleado, tipo_licencia):
    novedad_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]
    resp = cliente_supervisor.post(f"/api/v1/novedades/{novedad_id}/aprobar/")
    assert resp.status_code == 403  # R11


def test_rrhh_aprueba_novedad(cliente_rrhh, cliente_supervisor, empleado, tipo_licencia):
    novedad_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]
    resp = cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/aprobar/")
    assert resp.status_code == 200, resp.data
    assert resp.data["estado"] == EstadoNovedad.APROBADA
    novedad = Novedad.objects.get(pk=novedad_id)
    assert novedad.aprobada_por is not None and novedad.aprobada_en is not None


def test_no_se_aprueba_dos_veces(cliente_rrhh, cliente_supervisor, empleado, tipo_licencia):
    novedad_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/aprobar/")
    resp = cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/aprobar/")
    assert resp.status_code == 400
    assert "estado" in resp.data["campos"]


# ---------- Cadena de prórrogas (§6 bis) ----------
def _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia):
    novedad_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/aprobar/")
    return novedad_id


def test_prorrogar_crea_eslabon_contiguo_pendiente(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    resp = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20", "motivo": "Sigue con yeso"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    prorroga = Novedad.objects.get(pk=resp.data["id"])
    assert prorroga.novedad_origen_id == madre_id  # apunta a la madre
    assert prorroga.fecha_desde.isoformat() == "2025-03-11"  # contigua (madre terminó el 10)
    assert prorroga.estado == EstadoNovedad.REGISTRADA  # RP5: nace pendiente
    assert prorroga.tipo_novedad_id == tipo_licencia.id  # RP7: hereda el tipo


def test_no_se_prorroga_no_aprobada(cliente_supervisor, empleado, tipo_licencia):
    novedad_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]
    resp = cliente_supervisor.post(
        f"/api/v1/novedades/{novedad_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )
    assert resp.status_code == 400  # RP2
    assert "estado" in resp.data["campos"]


def test_no_se_prorroga_tipo_sin_prorroga(
    cliente_supervisor, cliente_rrhh, empleado, tipo_horas_extra
):
    novedad_id = _alta(
        cliente_supervisor, empleado, tipo_horas_extra, fecha_hasta=None, cantidad_horas="4.00"
    ).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/aprobar/")
    resp = cliente_supervisor.post(
        f"/api/v1/novedades/{novedad_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )
    assert resp.status_code == 400  # RP2 admite_prorroga=False
    assert "tipo_novedad" in resp.data["campos"]


def test_prorroga_debe_extender_de_verdad(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    resp = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-05"},  # antes de que termine la madre (10)
        format="json",
    )
    assert resp.status_code == 400  # RP3
    assert "fecha_hasta_nueva" in resp.data["campos"]


def test_cadena_y_vigencia_efectiva(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia):
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    # prórroga hasta el 20 y aprobarla
    prorroga_id = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    ).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{prorroga_id}/aprobar/")

    resp = cliente_rrhh.get(f"/api/v1/novedades/{madre_id}/cadena/")
    assert resp.status_code == 200, resp.data
    assert resp.data["vigencia_efectiva"]["desde"] == "2025-03-01"
    assert resp.data["vigencia_efectiva"]["hasta"] == "2025-03-20"
    assert resp.data["dias_totales"] == 20
    assert len(resp.data["prorrogas"]) == 1

    # pidiendo la cadena desde la prórroga se redirige a la madre
    resp2 = cliente_rrhh.get(f"/api/v1/novedades/{prorroga_id}/cadena/")
    assert resp2.data["madre"]["id"] == madre_id


def test_no_anular_madre_con_prorrogas_activas(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )
    resp = cliente_rrhh.post(f"/api/v1/novedades/{madre_id}/anular/")
    assert resp.status_code == 400  # RP6
    assert "estado" in resp.data["campos"]


# ---------- Listado ----------
def test_lista_colapsa_cadenas_por_defecto(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )
    # por defecto: solo la madre (1 fila), con badge de prórrogas
    resp = cliente_rrhh.get("/api/v1/novedades/")
    assert resp.data["count"] == 1
    assert resp.data["results"][0]["id"] == madre_id
    assert resp.data["results"][0]["cantidad_prorrogas"] == 1
    # expandidas: madre + prórroga
    resp2 = cliente_rrhh.get("/api/v1/novedades/?expandir_cadenas=true")
    assert resp2.data["count"] == 2
