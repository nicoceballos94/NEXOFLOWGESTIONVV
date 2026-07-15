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
        ocupa_periodo=True,
        requiere_certificado=True,
        admite_prorroga=True,
    )


@pytest.fixture
def tipo_falta():
    # Ojo: la falta ocupa el día pero NO justifica la ausencia (es injustificada).
    return TipoNovedad.objects.create(
        codigo="FALTA", nombre="Falta", justifica_ausencia=False, ocupa_periodo=True
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


def test_no_se_carga_novedad_a_empleado_egresado(cliente_supervisor, empresa, tipo_licencia):
    """Un empleado dado de baja (sin relación ACTIVA) no admite novedades nuevas."""
    egresado = Empleado.objects.create(legajo="0099", dni="39999888", nombre="Ex", apellido="Baja")
    RelacionLaboral.objects.create(
        empleado=egresado, empresa=empresa, fecha_ingreso="2020-01-01",
        fecha_egreso="2024-06-30", estado="FINALIZADA",
    )
    resp = _alta(cliente_supervisor, egresado, tipo_licencia)
    assert resp.status_code == 400, resp.data
    assert "empleado" in resp.data["campos"]


def test_no_se_carga_ausencia_sobre_otra_corriendo(cliente_supervisor, empleado, tipo_licencia):
    """Item 4: al alta se bloquea una ausencia que se solapa con otra ya vigente,
    aunque la anterior esté sólo REGISTRADA (pendiente)."""
    primera = _alta(cliente_supervisor, empleado, tipo_licencia)  # 03-01 → 03-10
    assert primera.status_code == 201, primera.data
    resp = _alta(
        cliente_supervisor, empleado, tipo_licencia,
        fecha_desde="2025-03-05", fecha_hasta="2025-03-15",  # se solapa con la anterior
    )
    assert resp.status_code == 400, resp.data
    assert "fecha_desde" in resp.data["campos"]


def test_ausencia_contigua_sin_solape_se_carga(cliente_supervisor, empleado, tipo_licencia):
    """Sin solapamiento (arranca al día siguiente) el alta pasa."""
    _alta(cliente_supervisor, empleado, tipo_licencia)  # 03-01 → 03-10
    resp = _alta(
        cliente_supervisor, empleado, tipo_licencia,
        fecha_desde="2025-03-11", fecha_hasta="2025-03-15",
    )
    assert resp.status_code == 201, resp.data


# ---------- Solapamiento entre tipos distintos ----------
def test_no_se_carga_falta_sobre_licencia(
    cliente_supervisor, empleado, tipo_licencia, tipo_falta
):
    """Una falta ocupa el día aunque no justifique la ausencia: no convive con una licencia."""
    _alta(cliente_supervisor, empleado, tipo_licencia)  # 03-01 → 03-10
    resp = _alta(
        cliente_supervisor, empleado, tipo_falta,
        fecha_desde="2025-03-05", fecha_hasta="2025-03-05",
    )
    assert resp.status_code == 400, resp.data
    assert "fecha_desde" in resp.data["campos"]


def test_no_se_carga_licencia_sobre_falta(
    cliente_supervisor, empleado, tipo_licencia, tipo_falta
):
    """Y al revés: la falta preexistente también bloquea."""
    _alta(
        cliente_supervisor, empleado, tipo_falta,
        fecha_desde="2025-03-05", fecha_hasta="2025-03-05",
    )
    resp = _alta(cliente_supervisor, empleado, tipo_licencia)  # 03-01 → 03-10, pisa el 03-05
    assert resp.status_code == 400, resp.data


def test_novedad_rechazada_libera_el_periodo(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia, tipo_falta
):
    """La excepción a la regla: una novedad RECHAZADA no ocupa nada."""
    primera_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{primera_id}/rechazar/", {"motivo": "sin cert"},
                      format="json")
    resp = _alta(
        cliente_supervisor, empleado, tipo_falta,
        fecha_desde="2025-03-05", fecha_hasta="2025-03-05",
    )
    assert resp.status_code == 201, resp.data


def test_novedad_cerrada_sigue_ocupando_el_periodo(
    cliente_supervisor, empleado, tipo_licencia, tipo_falta
):
    """Una licencia CERRADA ya transcurrió: nadie puede cargar una falta encima."""
    novedad_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]
    Novedad.objects.filter(pk=novedad_id).update(estado=EstadoNovedad.CERRADA)
    resp = _alta(
        cliente_supervisor, empleado, tipo_falta,
        fecha_desde="2025-03-05", fecha_hasta="2025-03-05",
    )
    assert resp.status_code == 400, resp.data


def test_licencia_abierta_bloquea_lo_que_venga_despues(
    cliente_supervisor, empleado, tipo_licencia, tipo_falta
):
    """Una novedad sin fecha de fin corre sin fin: ocupa todo lo posterior a su inicio."""
    abierta = _alta(cliente_supervisor, empleado, tipo_licencia, fecha_hasta=None)
    assert abierta.status_code == 201, abierta.data
    resp = _alta(
        cliente_supervisor, empleado, tipo_falta,
        fecha_desde="2025-06-01", fecha_hasta="2025-06-01",  # meses después, pero la abierta corre
    )
    assert resp.status_code == 400, resp.data


def test_horas_extra_conviven_con_una_licencia(
    cliente_supervisor, empleado, tipo_licencia, tipo_horas_extra
):
    """Las horas extra no ocupan el período: no las alcanza la regla."""
    _alta(cliente_supervisor, empleado, tipo_licencia)  # 03-01 → 03-10
    resp = _alta(
        cliente_supervisor, empleado, tipo_horas_extra,
        fecha_desde="2025-03-05", fecha_hasta=None, cantidad_horas="4.00",
    )
    assert resp.status_code == 201, resp.data


# ---------- Edición ----------
def test_editar_no_puede_solapar_otra_novedad(
    cliente_supervisor, empleado, tipo_licencia, tipo_falta
):
    """El agujero grande: el alta validaba, pero el PATCH movía las fechas encima de otra."""
    _alta(cliente_supervisor, empleado, tipo_licencia)  # 03-01 → 03-10
    falta_id = _alta(
        cliente_supervisor, empleado, tipo_falta,
        fecha_desde="2025-06-01", fecha_hasta="2025-06-01",
    ).data["id"]
    resp = cliente_supervisor.patch(
        f"/api/v1/novedades/{falta_id}/",
        {"fecha_desde": "2025-03-05", "fecha_hasta": "2025-03-05"},  # se mete en la licencia
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "fecha_desde" in resp.data["campos"]


def test_editar_fechas_sin_solape_pasa(cliente_supervisor, empleado, tipo_licencia):
    """Editar la propia novedad no se cuenta como solapamiento consigo misma."""
    novedad_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]
    resp = cliente_supervisor.patch(
        f"/api/v1/novedades/{novedad_id}/",
        {"fecha_hasta": "2025-03-12"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["fecha_hasta"] == "2025-03-12"


def test_editar_no_admite_fin_anterior_al_inicio(cliente_supervisor, empleado, tipo_licencia):
    novedad_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]
    resp = cliente_supervisor.patch(
        f"/api/v1/novedades/{novedad_id}/", {"fecha_hasta": "2025-02-20"}, format="json"
    )
    assert resp.status_code == 400, resp.data
    assert "fecha_hasta" in resp.data["campos"]


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


def test_prorroga_no_pisa_una_novedad_pendiente(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia, tipo_falta
):
    """RP4 miraba solo las aprobadas: una falta pendiente en el medio no frenaba la prórroga."""
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    _alta(  # falta REGISTRADA después de la madre (03-10), sin solaparla
        cliente_supervisor, empleado, tipo_falta,
        fecha_desde="2025-03-15", fecha_hasta="2025-03-15",
    )
    resp = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},  # 03-11 → 03-20 pisa la falta del 03-15
        format="json",
    )
    assert resp.status_code == 400, resp.data
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


def test_no_se_edita_el_inicio_de_una_prorroga(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    """B2: la prórroga nace contigua a la cadena (RP3). El front deshabilita el campo, pero
    el contrato es la API: por PATCH se podía abrir un agujero o pisar la madre, y la
    validación de solapamiento no lo veía (excluye la propia cadena a propósito)."""
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    prorroga_id = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    ).data["id"]
    resp = cliente_supervisor.patch(
        f"/api/v1/novedades/{prorroga_id}/",
        {"fecha_desde": "2025-03-05"},  # se metería adentro de la madre (03-01 → 03-10)
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "fecha_desde" in resp.data["campos"]
    assert Novedad.objects.get(pk=prorroga_id).fecha_desde.isoformat() == "2025-03-11"


def test_no_se_cambia_el_tipo_de_una_prorroga(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia, tipo_falta
):
    """RP7: la prórroga hereda el tipo de la madre; el PATCH no puede romper la herencia."""
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    prorroga_id = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    ).data["id"]
    resp = cliente_supervisor.patch(
        f"/api/v1/novedades/{prorroga_id}/", {"tipo_novedad": tipo_falta.id}, format="json"
    )
    assert resp.status_code == 400, resp.data
    assert "tipo_novedad" in resp.data["campos"]


def test_la_prorroga_sigue_editando_su_fin_y_su_motivo(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    """El blindaje es quirúrgico: lo que la cadena no fija se sigue editando."""
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    prorroga_id = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    ).data["id"]
    resp = cliente_supervisor.patch(
        f"/api/v1/novedades/{prorroga_id}/",
        {"fecha_hasta": "2025-03-25", "motivo": "Sigue sin alta"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["fecha_hasta"] == "2025-03-25"


def test_reenviar_la_misma_fecha_desde_no_es_una_edicion(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    """Un PATCH que repite el valor actual no cambia nada: no hay por qué rechazarlo."""
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    prorroga_id = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    ).data["id"]
    resp = cliente_supervisor.patch(
        f"/api/v1/novedades/{prorroga_id}/",
        {"fecha_desde": "2025-03-11", "motivo": "Con parte médico"},
        format="json",
    )
    assert resp.status_code == 200, resp.data


def test_no_se_prorroga_con_una_prorroga_pendiente(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    """`vigencia_efectiva` solo avanza con las prórrogas APROBADAS: prorrogar de nuevo con una
    pendiente calculaba el mismo `fecha_desde` y creaba dos eslabones pisados."""
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )
    resp = cliente_supervisor.post(  # sin aprobar la anterior
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-30"},
        format="json",
    )
    assert resp.status_code == 400, resp.data
    assert "estado" in resp.data["campos"]
    assert Novedad.objects.filter(novedad_origen_id=madre_id).count() == 1


def test_la_cadena_avanza_aprobando_cada_eslabon(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    """Y con la prórroga aprobada, la siguiente arranca contigua a la nueva vigencia."""
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    primera_id = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    ).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{primera_id}/aprobar/")
    resp = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-30"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["fecha_desde"] == "2025-03-21"  # contigua a la prórroga aprobada


# ---------- Respaldo en la base (B3) ----------
def test_la_base_rechaza_novedades_solapadas_aunque_se_saltee_el_service(
    empleado, tipo_licencia
):
    """El ExclusionConstraint es la red de seguridad de `_validar_sin_solapamiento`: una
    escritura que no pase por el service (bulk, shell, admin, SQL) tampoco puede solapar."""
    from django.db import IntegrityError

    Novedad.objects.create(
        empleado=empleado, tipo_novedad=tipo_licencia,
        fecha_desde="2025-03-01", fecha_hasta="2025-03-10",
    )
    with pytest.raises(IntegrityError):
        Novedad.objects.create(
            empleado=empleado, tipo_novedad=tipo_licencia,
            fecha_desde="2025-03-05", fecha_hasta="2025-03-15",
        )


def test_la_base_deja_convivir_lo_que_no_ocupa_periodo(empleado, tipo_licencia, tipo_horas_extra):
    """El constraint respeta el flag: las horas extra conviven con la licencia."""
    Novedad.objects.create(
        empleado=empleado, tipo_novedad=tipo_licencia,
        fecha_desde="2025-03-01", fecha_hasta="2025-03-10",
    )
    extra = Novedad.objects.create(
        empleado=empleado, tipo_novedad=tipo_horas_extra,
        fecha_desde="2025-03-05", cantidad_horas="4.00",
    )
    assert extra.pk is not None
    assert extra.ocupa_periodo is False  # copiado del tipo por save()


def test_la_base_libera_el_periodo_de_una_anulada(empleado, tipo_licencia):
    """RECHAZADA/ANULADA quedan fuera de la condición del constraint, como en el service."""
    primera = Novedad.objects.create(
        empleado=empleado, tipo_novedad=tipo_licencia,
        fecha_desde="2025-03-01", fecha_hasta="2025-03-10",
    )
    primera.estado = EstadoNovedad.ANULADA
    primera.save(update_fields=["estado"])
    segunda = Novedad.objects.create(
        empleado=empleado, tipo_novedad=tipo_licencia,
        fecha_desde="2025-03-05", fecha_hasta="2025-03-15",
    )
    assert segunda.pk is not None


def test_la_base_ve_la_novedad_abierta_como_rango_sin_fin(empleado, tipo_licencia, tipo_falta):
    """fecha_hasta NULL = daterange sin límite superior: pisa todo lo posterior."""
    from django.db import IntegrityError

    Novedad.objects.create(
        empleado=empleado, tipo_novedad=tipo_licencia, fecha_desde="2025-03-01", fecha_hasta=None
    )
    with pytest.raises(IntegrityError):
        Novedad.objects.create(
            empleado=empleado, tipo_novedad=tipo_falta,
            fecha_desde="2025-09-01", fecha_hasta="2025-09-01",
        )


def test_la_cadena_de_prorrogas_no_choca_con_el_constraint(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    """La cadena es contigua, no solapada: el flujo normal nunca toca el constraint."""
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    resp = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )
    assert resp.status_code == 201, resp.data


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
