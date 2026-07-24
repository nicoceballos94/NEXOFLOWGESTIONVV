"""Tests de la app novedades: alta, permisos, transiciones y cadena de prórrogas (§6 bis).

Cubre las reglas críticas del MVP1: R11 (solo RRHH aprueba), RP2/RP3/RP4/RP5/RP7 de la
cadena, RP6 (no anular la madre con prórrogas activas) y la vigencia efectiva calculada.
"""
from datetime import date

import pytest
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.empleados.models import Empleado, RelacionLaboral
from apps.novedades import services
from apps.novedades.models import EstadoNovedad, Novedad, TipoNovedad
from apps.organizacion.models import Empresa, Puesto, Sector
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
    empresa = Empresa.objects.create(nombre="VIAL VICTORIA")
    empresa._sector_prueba = Sector.objects.create(nombre="Operaciones")
    empresa._puesto_prueba = Puesto.objects.create(
        nombre="Chofer", sector=empresa._sector_prueba
    )
    return empresa


@pytest.fixture
def supervisor(crear_usuario):
    return crear_usuario(username="super", rol=roles.SUPERVISOR)


@pytest.fixture
def empleado(empresa, supervisor):
    emp = Empleado.objects.create(legajo="0001", dni="30111222", nombre="Juan", apellido="Pérez")
    RelacionLaboral.objects.create(
        empleado=emp,
        empresa=empresa,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        supervisor=supervisor,
        fecha_ingreso="2024-01-10",
    )
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
def cliente_supervisor(supervisor):
    cliente = APIClient()
    cliente.force_authenticate(supervisor)
    return cliente


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


@pytest.mark.parametrize(
    ("campo", "valor"),
    (
        ("fecha_turno_praxis", "2025-02-28"),
        ("fecha_fin_estimada", "2025-02-28"),
        ("fecha_reintegro", "2025-03-10"),
        ("certificado_recibido_en", "2099-01-01"),
    ),
)
def test_alta_rechaza_cronologia_incoherente_de_seguimiento(
    cliente_supervisor,
    empleado,
    tipo_licencia,
    campo,
    valor,
):
    respuesta = _alta(
        cliente_supervisor,
        empleado,
        tipo_licencia,
        **{campo: valor},
    )

    assert respuesta.status_code == 400
    assert campo in respuesta.data["campos"]


def test_rol_mixto_supervisor_empleado_une_equipo_y_novedades_propias(
    cliente_supervisor,
    cliente_rrhh,
    supervisor,
    empleado,
    empresa,
    tipo_licencia,
):
    from django.contrib.auth.models import Group

    supervisor.groups.add(Group.objects.get_or_create(name=roles.EMPLEADO)[0])
    propio = Empleado.objects.create(
        legajo="0900",
        dni="33444555",
        nombre="Sofía",
        apellido="Jefa",
        usuario=supervisor,
    )
    RelacionLaboral.objects.create(
        empleado=propio,
        empresa=empresa,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        fecha_ingreso="2024-02-01",
    )
    del_equipo = _alta(
        cliente_supervisor,
        empleado,
        tipo_licencia,
        motivo="Diagnóstico del equipo",
    )
    propia = _alta(
        cliente_rrhh,
        propio,
        tipo_licencia,
        motivo="Diagnóstico propio",
    )
    assert del_equipo.status_code == 201
    assert propia.status_code == 201

    lista = cliente_supervisor.get("/api/v1/novedades/")
    assert {fila["id"] for fila in lista.data["results"]} == {
        del_equipo.data["id"],
        propia.data["id"],
    }
    detalle_propio = cliente_supervisor.get(
        f"/api/v1/novedades/{propia.data['id']}/"
    )
    assert detalle_propio.data["motivo"] == "Diagnóstico propio"
    detalle_equipo = cliente_supervisor.get(
        f"/api/v1/novedades/{del_equipo.data['id']}/"
    )
    assert "motivo" not in detalle_equipo.data


def test_supervisor_no_recibe_textos_medicos_ni_los_infiere_por_busqueda(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    creada = _alta(
        cliente_supervisor,
        empleado,
        tipo_licencia,
        motivo="Diagnóstico reservado",
        observaciones="Tratamiento confidencial",
        certificado_recibido_en="2025-03-02",
    )

    assert creada.status_code == 201, creada.data
    for campo in (
        "motivo",
        "observaciones",
        "motivo_rechazo",
        "motivo_anulacion",
        "certificado_recibido_en",
    ):
        assert campo not in creada.data
    assert creada.data["fecha_desde"] == "2025-03-01"
    assert creada.data["estado"] == EstadoNovedad.REGISTRADA

    detalle = cliente_supervisor.get(f"/api/v1/novedades/{creada.data['id']}/")
    assert detalle.status_code == 200
    assert "motivo" not in detalle.data

    busqueda = cliente_supervisor.get(
        "/api/v1/novedades/?q=Diagnóstico%20reservado"
    )
    assert busqueda.status_code == 200
    assert busqueda.data["count"] == 0

    detalle_rrhh = cliente_rrhh.get(f"/api/v1/novedades/{creada.data['id']}/")
    assert detalle_rrhh.data["motivo"] == "Diagnóstico reservado"
    assert detalle_rrhh.data["observaciones"] == "Tratamiento confidencial"


def test_alta_por_dias_calcula_fecha_hasta(cliente_supervisor, empleado, tipo_licencia):
    resp = _alta(cliente_supervisor, empleado, tipo_licencia, fecha_hasta=None, dias=5)
    assert resp.status_code == 201, resp.data
    assert resp.data["fecha_hasta"] == "2025-03-05"  # desde + (5-1) días


def test_falta_sin_fin_explicito_se_normaliza_a_un_solo_dia(
    cliente_supervisor, empleado, tipo_falta, tipo_licencia
):
    falta = _alta(
        cliente_supervisor,
        empleado,
        tipo_falta,
        fecha_desde="2025-03-01",
        fecha_hasta=None,
    )
    assert falta.status_code == 201, falta.data
    assert falta.data["fecha_hasta"] == "2025-03-01"

    posterior = _alta(
        cliente_supervisor,
        empleado,
        tipo_licencia,
        fecha_desde="2025-03-02",
        fecha_hasta="2025-03-03",
    )
    assert posterior.status_code == 201, posterior.data


def test_horas_extra_exige_cantidad(cliente_supervisor, empleado, tipo_horas_extra):
    resp = _alta(cliente_supervisor, empleado, tipo_horas_extra, fecha_hasta=None)
    assert resp.status_code == 400
    assert "cantidad_horas" in resp.data["campos"]


def test_empleado_no_puede_cargar_novedad(cliente_empleado, empleado, tipo_licencia):
    resp = _alta(cliente_empleado, empleado, tipo_licencia)
    assert resp.status_code == 403


def test_supervisor_no_puede_cargar_novedad_de_otro_equipo(
    cliente_supervisor,
    crear_usuario,
    empresa,
    tipo_licencia,
):
    otro_supervisor = crear_usuario(
        username="supervisor-ajeno",
        rol=roles.SUPERVISOR,
    )
    ajeno = Empleado.objects.create(
        legajo="0098",
        dni="39999777",
        nombre="Otro",
        apellido="Equipo",
    )
    RelacionLaboral.objects.create(
        empleado=ajeno,
        empresa=empresa,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        supervisor=otro_supervisor,
        fecha_ingreso="2024-01-10",
    )

    resp = _alta(cliente_supervisor, ajeno, tipo_licencia)

    assert resp.status_code == 403, resp.data
    assert not Novedad.objects.filter(empleado=ajeno).exists()
    assert not RegistroAuditoria.objects.filter(
        accion=Accion.NOVEDAD_CREADA,
        empleado=ajeno,
    ).exists()


def test_service_revalida_scope_si_reasignan_relacion_antes_de_mutar(
    supervisor,
    crear_usuario,
    empleado,
    tipo_licencia,
):
    novedad = services.crear_novedad(
        actor=supervisor,
        datos={
            "empleado": empleado,
            "tipo_novedad": tipo_licencia,
            "fecha_desde": date(2025, 3, 1),
            "fecha_hasta": date(2025, 3, 10),
            "motivo": "Carga válida antes de reasignar",
        },
    )
    otro_supervisor = crear_usuario(
        username="nuevo-supervisor",
        rol=roles.SUPERVISOR,
    )
    relacion = empleado.relacion_activa
    relacion.supervisor = otro_supervisor
    relacion.save(update_fields=["supervisor"])

    with pytest.raises(PermissionDenied):
        services.tomar_novedad(actor=supervisor, novedad=novedad)

    novedad.refresh_from_db()
    assert novedad.estado == EstadoNovedad.REGISTRADA


def test_no_se_carga_novedad_a_empleado_egresado(cliente_supervisor, empresa, tipo_licencia):
    """Un empleado dado de baja (sin relación ACTIVA) no admite novedades nuevas."""
    egresado = Empleado.objects.create(legajo="0099", dni="39999888", nombre="Ex", apellido="Baja")
    RelacionLaboral.objects.create(
        empleado=egresado,
        empresa=empresa,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        fecha_ingreso="2020-01-01",
        fecha_egreso="2024-06-30",
        motivo_egreso="RENUNCIA",
        estado="FINALIZADA",
    )
    resp = _alta(cliente_supervisor, egresado, tipo_licencia)
    assert resp.status_code == 400, resp.data
    assert "relacion_laboral" in resp.data["campos"]


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


def test_supervisor_no_sobrescribe_campos_confidenciales_que_no_puede_leer(
    cliente_rrhh,
    cliente_supervisor,
    empleado,
    tipo_licencia,
):
    creada = _alta(
        cliente_rrhh,
        empleado,
        tipo_licencia,
        motivo="Diagnóstico reservado",
        observaciones="Tratamiento confidencial",
    )
    assert creada.status_code == 201, creada.data

    resp = cliente_supervisor.patch(
        f"/api/v1/novedades/{creada.data['id']}/",
        {
            "motivo": "Sobrescrito a ciegas",
            "certificado_recibido_en": "2025-03-03",
        },
        format="json",
    )

    assert resp.status_code == 403, resp.data
    novedad = Novedad.objects.get(pk=creada.data["id"])
    assert novedad.motivo == "Diagnóstico reservado"
    assert novedad.certificado_recibido_en is None


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


def test_no_se_cierra_una_novedad_abierta_sin_fecha_de_fin(
    cliente_rrhh, empleado, tipo_licencia
):
    novedad_id = _alta(
        cliente_rrhh,
        empleado,
        tipo_licencia,
        fecha_hasta=None,
    ).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/aprobar/")

    resp = cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/cerrar/")

    assert resp.status_code == 400, resp.data
    assert "fecha_hasta" in resp.data["campos"]
    assert Novedad.objects.get(pk=novedad_id).estado == EstadoNovedad.APROBADA


def test_editar_no_mueve_novedad_fuera_de_la_vigencia_laboral(
    cliente_supervisor,
    empleado,
    tipo_licencia,
):
    novedad_id = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]

    respuesta = cliente_supervisor.patch(
        f"/api/v1/novedades/{novedad_id}/",
        {"fecha_desde": "2023-12-31", "fecha_hasta": "2024-01-05"},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "fecha_desde" in respuesta.data["campos"]
    assert Novedad.objects.get(pk=novedad_id).estado == EstadoNovedad.REGISTRADA


def test_cerrar_novedad_abierta_fija_fin_y_lo_audita_en_la_misma_accion(
    cliente_rrhh, empleado, tipo_licencia
):
    novedad_id = _alta(
        cliente_rrhh,
        empleado,
        tipo_licencia,
        fecha_hasta=None,
    ).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/aprobar/")

    resp = cliente_rrhh.post(
        f"/api/v1/novedades/{novedad_id}/cerrar/",
        {"fecha_hasta": "2025-03-15"},
        format="json",
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["estado"] == EstadoNovedad.CERRADA
    assert resp.data["fecha_hasta"] == "2025-03-15"
    novedad = Novedad.objects.get(pk=novedad_id)
    assert novedad.fecha_hasta.isoformat() == "2025-03-15"
    evento = RegistroAuditoria.objects.get(
        accion=Accion.NOVEDAD_CERRADA,
        objeto_id=novedad_id,
    )
    assert evento.valores_antes["fecha_hasta"] is None
    assert evento.valores_despues["fecha_hasta"] == "2025-03-15"
    assert evento.valores_despues["estado"] == EstadoNovedad.CERRADA


def test_cerrar_rechaza_fin_anterior_y_no_reescribe_un_fin_aprobado(
    cliente_rrhh, empleado, tipo_licencia
):
    abierta = _alta(
        cliente_rrhh,
        empleado,
        tipo_licencia,
        fecha_hasta=None,
    ).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{abierta}/aprobar/")

    anterior = cliente_rrhh.post(
        f"/api/v1/novedades/{abierta}/cerrar/",
        {"fecha_hasta": "2025-02-28"},
        format="json",
    )

    assert anterior.status_code == 400, anterior.data
    assert "fecha_hasta" in anterior.data["campos"]
    assert Novedad.objects.get(pk=abierta).estado == EstadoNovedad.APROBADA
    cliente_rrhh.post(
        f"/api/v1/novedades/{abierta}/anular/",
        {"motivo": "Caso de prueba terminado"},
        format="json",
    )

    finita = _alta(
        cliente_rrhh,
        empleado,
        tipo_licencia,
        fecha_desde="2025-04-01",
        fecha_hasta="2025-04-10",
    ).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{finita}/aprobar/")
    reescritura = cliente_rrhh.post(
        f"/api/v1/novedades/{finita}/cerrar/",
        {"fecha_hasta": "2025-04-20"},
        format="json",
    )

    assert reescritura.status_code == 400, reescritura.data
    finita_db = Novedad.objects.get(pk=finita)
    assert finita_db.estado == EstadoNovedad.APROBADA
    assert finita_db.fecha_hasta.isoformat() == "2025-04-10"


def test_cerrar_una_novedad_finita_deja_actor_y_momento(
    cliente_rrhh, empleado, tipo_licencia
):
    novedad_id = _alta(cliente_rrhh, empleado, tipo_licencia).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/aprobar/")

    resp = cliente_rrhh.post(f"/api/v1/novedades/{novedad_id}/cerrar/")

    assert resp.status_code == 200, resp.data
    assert resp.data["estado"] == EstadoNovedad.CERRADA
    novedad = Novedad.objects.get(pk=novedad_id)
    assert novedad.cerrada_por is not None
    assert novedad.cerrada_en is not None


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


def test_no_se_prorroga_si_el_tipo_fue_desactivado(
    cliente_supervisor,
    cliente_rrhh,
    empleado,
    tipo_licencia,
):
    madre_id = _crear_licencia_aprobada(
        cliente_supervisor,
        cliente_rrhh,
        empleado,
        tipo_licencia,
    )
    # Simula dato legado/cambio externo: el service debe releer el catálogo bajo lock.
    TipoNovedad.objects.filter(pk=tipo_licencia.pk).update(activo=False)

    respuesta = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "tipo_novedad" in respuesta.data["campos"]


def test_filtro_desde_usa_fin_de_prorroga_aprobada(
    cliente_supervisor,
    cliente_rrhh,
    empleado,
    tipo_licencia,
):
    madre_id = _crear_licencia_aprobada(
        cliente_supervisor,
        cliente_rrhh,
        empleado,
        tipo_licencia,
    )
    prorroga = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )
    assert prorroga.status_code == 201, prorroga.data
    assert cliente_rrhh.post(
        f"/api/v1/novedades/{prorroga.data['id']}/aprobar/"
    ).status_code == 200

    respuesta = cliente_rrhh.get("/api/v1/novedades/?desde=2025-03-15")

    assert respuesta.status_code == 200
    assert [fila["id"] for fila in respuesta.data["results"]] == [madre_id]


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


def test_no_anula_prorroga_intermedia_y_deja_un_hueco_en_la_cadena(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    madre_id = _crear_licencia_aprobada(
        cliente_supervisor,
        cliente_rrhh,
        empleado,
        tipo_licencia,
    )
    primera = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )
    assert primera.status_code == 201
    assert cliente_rrhh.post(
        f"/api/v1/novedades/{primera.data['id']}/aprobar/"
    ).status_code == 200
    segunda = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-30"},
        format="json",
    )
    assert segunda.status_code == 201

    bloqueada = cliente_rrhh.post(
        f"/api/v1/novedades/{primera.data['id']}/anular/",
        {"motivo": "Carga equivocada"},
        format="json",
    )

    assert bloqueada.status_code == 400
    assert "posteriores" in str(bloqueada.data).lower()
    assert (
        Novedad.objects.get(pk=primera.data["id"]).estado
        == EstadoNovedad.APROBADA
    )


def test_no_anular_madre_con_prorrogas_activas(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    )
    resp = cliente_rrhh.post(
        f"/api/v1/novedades/{madre_id}/anular/",
        {"motivo": "Carga duplicada"},
        format="json",
    )
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


def test_supervisor_edita_fin_de_prorroga_pero_no_sobrescribe_motivo_reservado(
    cliente_supervisor, cliente_rrhh, empleado, tipo_licencia
):
    """El blindaje es quirúrgico: opera fechas, pero no texto clínico que no puede leer."""
    madre_id = _crear_licencia_aprobada(cliente_supervisor, cliente_rrhh, empleado, tipo_licencia)
    prorroga_id = cliente_supervisor.post(
        f"/api/v1/novedades/{madre_id}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    ).data["id"]
    resp = cliente_supervisor.patch(
        f"/api/v1/novedades/{prorroga_id}/",
        {"fecha_hasta": "2025-03-25"},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["fecha_hasta"] == "2025-03-25"

    bloqueada = cliente_supervisor.patch(
        f"/api/v1/novedades/{prorroga_id}/",
        {"motivo": "Sigue sin alta"},
        format="json",
    )
    assert bloqueada.status_code == 403
    assert Novedad.objects.get(pk=prorroga_id).motivo == ""


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
        {"fecha_desde": "2025-03-11"},
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
    primera.motivo_anulacion = "Dato de prueba"
    primera.save(update_fields=["estado", "motivo_anulacion"])
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


def test_filtro_empresa_incluye_novedad_sin_relacion(
    cliente_rrhh, empleado, empresa, tipo_licencia
):
    """Una novedad sin `relacion_laboral` (dato importado fuera del alta) no debe caerse
    del filtro por empresa: la empresa se resuelve por las relaciones del empleado."""
    huerfana = Novedad.objects.create(
        empleado=empleado, tipo_novedad=tipo_licencia, relacion_laboral=None,
        fecha_desde="2025-05-01", fecha_hasta="2025-05-05", motivo="Importada",
    )
    resp = cliente_rrhh.get(f"/api/v1/novedades/?empresa={empresa.id}")
    assert resp.status_code == 200, resp.data
    assert [n["id"] for n in resp.data["results"]] == [huerfana.id]


def test_filtro_empresa_excluye_otra_empresa(cliente_rrhh, empleado, tipo_licencia):
    """El fallback por empleado no debe traer novedades de una empresa ajena."""
    otra = Empresa.objects.create(nombre="OTRA SA")
    Novedad.objects.create(
        empleado=empleado, tipo_novedad=tipo_licencia, relacion_laboral=None,
        fecha_desde="2025-05-01", fecha_hasta="2025-05-05", motivo="Importada",
    )
    resp = cliente_rrhh.get(f"/api/v1/novedades/?empresa={otra.id}")
    assert resp.status_code == 200, resp.data
    assert resp.data["count"] == 0


def test_filtro_empresa_usa_la_relacion_del_hecho_no_todo_el_historial(
    cliente_rrhh, empleado, empresa, tipo_licencia
):
    """Una relación histórica en otra empresa no contamina el filtro del hecho actual."""
    otra = Empresa.objects.create(nombre="OTRA SA")
    RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=otra,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        fecha_ingreso="2023-01-01",
        fecha_egreso="2023-12-31",
        motivo_egreso="RENUNCIA",
        estado="FINALIZADA",
    )
    novedad = Novedad.objects.create(
        empleado=empleado,
        tipo_novedad=tipo_licencia,
        relacion_laboral=empleado.relacion_activa,
        fecha_desde="2025-05-01", fecha_hasta="2025-05-05", motivo="Importada",
    )
    resp = cliente_rrhh.get(f"/api/v1/novedades/?empresa={empresa.id}")
    assert [fila["id"] for fila in resp.data["results"]] == [novedad.id]


# ---------- Adjuntos: la bitácora del hecho ----------
@pytest.fixture
def media_temporal(settings, tmp_path):
    """MEDIA_ROOT propio por test: los archivos subidos no ensucian el repo ni se pisan."""
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _archivo(nombre="certificado.pdf", contenido=None):
    import base64

    from django.core.files.uploadedfile import SimpleUploadedFile

    if contenido is None:
        if nombre.lower().endswith(".png"):
            contenido = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
                "+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            content_type = "image/png"
        else:
            contenido = b"%PDF-1.4 certificado"
            content_type = "application/pdf"
    else:
        content_type = "application/octet-stream"
    return SimpleUploadedFile(nombre, contenido, content_type=content_type)


def test_la_novedad_junta_varios_adjuntos_sin_pisar_ninguno(
    cliente_rrhh, empleado, tipo_licencia, media_temporal
):
    """La diferencia con el documento del empleado: acá NADA se pisa. Una licencia junta el
    certificado, los estudios y la radiografía, y todos conviven — eso es la bitácora."""
    nov = _alta(cliente_rrhh, empleado, tipo_licencia).data["id"]
    for nombre in ("certificado.pdf", "estudio.pdf", "radiografia.png"):
        resp = cliente_rrhh.post(
            f"/api/v1/novedades/{nov}/adjuntos/",
            {"archivo": _archivo(nombre), "descripcion": f"desc de {nombre}"},
            format="multipart",
        )
        assert resp.status_code == 201, resp.data

    resp = cliente_rrhh.get(f"/api/v1/novedades/{nov}/adjuntos/")
    assert resp.status_code == 200
    # Los tres siguen ahí, en orden de llegada, con su nombre real: en una bitácora saber
    # cuál era la radiografía y cuál el certificado ES el dato (no hay tipo que lo diga).
    assert [a["nombre_original"] for a in resp.data] == [
        "certificado.pdf", "estudio.pdf", "radiografia.png"
    ]
    assert resp.data[0]["subido_por"] == "rrhh"


def test_el_adjunto_se_descarga_con_su_nombre(
    cliente_rrhh, empleado, tipo_licencia, media_temporal
):
    from apps.novedades.models import AdjuntoNovedad

    nov = _alta(cliente_rrhh, empleado, tipo_licencia).data["id"]
    creado = cliente_rrhh.post(
        f"/api/v1/novedades/{nov}/adjuntos/",
        {"archivo": _archivo("alta-medica.pdf", b"%PDF-1.4 alta")},
        format="multipart",
    )
    adj = AdjuntoNovedad.objects.get(pk=creado.data["id"])
    # En disco es un UUID bajo novedades/<id>/: sin PII y no adivinable.
    assert adj.archivo.name.startswith(f"novedades/{nov}/")
    assert "alta-medica" not in adj.archivo.name

    resp = cliente_rrhh.get(creado.data["archivo_url"])
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content) == b"%PDF-1.4 alta"
    assert 'filename="alta-medica.pdf"' in resp["Content-Disposition"]


def test_el_certificado_se_puede_adjuntar_despues_de_cerrada(
    cliente_rrhh, empleado, tipo_licencia, media_temporal
):
    """El papel llega tarde: el certificado suele aparecer días después del hecho. Si el
    estado bloqueara el adjunto, habría que pelearle al sistema justo cuando aparece."""
    nov = _alta(cliente_rrhh, empleado, tipo_licencia).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{nov}/aprobar/")
    Novedad.objects.filter(pk=nov).update(estado=EstadoNovedad.CERRADA)
    resp = cliente_rrhh.post(
        f"/api/v1/novedades/{nov}/adjuntos/", {"archivo": _archivo()}, format="multipart"
    )
    assert resp.status_code == 201, resp.data


def test_quitar_adjunto_se_lleva_el_archivo(
    cliente_rrhh, empleado, tipo_licencia, media_temporal, django_capture_on_commit_callbacks
):
    from apps.novedades.models import AdjuntoNovedad

    nov = _alta(cliente_rrhh, empleado, tipo_licencia).data["id"]
    adj_id = cliente_rrhh.post(
        f"/api/v1/novedades/{nov}/adjuntos/", {"archivo": _archivo()}, format="multipart"
    ).data["id"]
    ruta = media_temporal / AdjuntoNovedad.objects.get(pk=adj_id).archivo.name
    assert ruta.exists()

    with django_capture_on_commit_callbacks(execute=True):
        resp = cliente_rrhh.delete(f"/api/v1/novedades/{nov}/adjuntos/{adj_id}/")
    assert resp.status_code == 204
    assert not ruta.exists(), "el binario quedó huérfano en MEDIA_ROOT"


def test_cada_prorroga_guarda_su_propio_respaldo(
    cliente_rrhh, empleado, tipo_licencia, media_temporal
):
    """El adjunto cae en el eslabón que corresponde: el certificado inicial en la madre, el
    de la extensión en la prórroga. Así la cadena queda con la cronología real."""
    madre = _alta(cliente_rrhh, empleado, tipo_licencia).data["id"]
    cliente_rrhh.post(f"/api/v1/novedades/{madre}/aprobar/")
    prorroga = cliente_rrhh.post(
        f"/api/v1/novedades/{madre}/prorrogar/",
        {"fecha_hasta_nueva": "2025-03-20"},
        format="json",
    ).data["id"]

    cliente_rrhh.post(
        f"/api/v1/novedades/{madre}/adjuntos/",
        {"archivo": _archivo("cert-inicial.pdf")}, format="multipart",
    )
    cliente_rrhh.post(
        f"/api/v1/novedades/{prorroga}/adjuntos/",
        {"archivo": _archivo("cert-extension.pdf")}, format="multipart",
    )

    de_madre = cliente_rrhh.get(f"/api/v1/novedades/{madre}/adjuntos/").data
    de_prorroga = cliente_rrhh.get(f"/api/v1/novedades/{prorroga}/adjuntos/").data
    assert [a["nombre_original"] for a in de_madre] == ["cert-inicial.pdf"]
    assert [a["nombre_original"] for a in de_prorroga] == ["cert-extension.pdf"]


def test_el_empleado_ve_su_certificado_pero_no_sube_ni_toca_ajenos(
    cliente_rrhh, empleado, tipo_licencia, crear_usuario, media_temporal
):
    """El empleado consulta lo suyo (CU §2: en MVP1 no carga nada) y las novedades de otros
    no existen para él: el selector las recorta y el pedido muere en 404, no en 403."""
    nov = _alta(cliente_rrhh, empleado, tipo_licencia).data["id"]
    creado = cliente_rrhh.post(
        f"/api/v1/novedades/{nov}/adjuntos/", {"archivo": _archivo()}, format="multipart"
    )
    assert creado.status_code == 201, creado.data

    # Usuario vinculado a ESE empleado: ve el adjunto de su licencia.
    usuario = crear_usuario(username="juanp", rol=roles.EMPLEADO)
    empleado.usuario = usuario
    empleado.save()
    propio = APIClient()
    propio.force_authenticate(usuario)
    assert propio.get(f"/api/v1/novedades/{nov}/adjuntos/").status_code == 200
    assert propio.get(creado.data["archivo_url"]).status_code == 200
    # Pero no carga respaldos ni borra.
    assert propio.post(
        f"/api/v1/novedades/{nov}/adjuntos/", {"archivo": _archivo()}, format="multipart"
    ).status_code == 403
    assert propio.delete(
        f"/api/v1/novedades/{nov}/adjuntos/{creado.data['id']}/"
    ).status_code == 403

    # Otro empleado, sin relación con esta novedad: para él no existe.
    ajeno = crear_usuario(username="curioso", rol=roles.EMPLEADO)
    otro = APIClient()
    otro.force_authenticate(ajeno)
    assert otro.get(f"/api/v1/novedades/{nov}/adjuntos/").status_code == 404
    assert otro.get(creado.data["archivo_url"]).status_code == 404


def test_supervisor_puede_adjuntar_pero_no_leer_descargar_ni_borrar_evidencia(
    cliente_supervisor,
    supervisor,
    empleado,
    tipo_licencia,
    media_temporal,
):
    nov = _alta(cliente_supervisor, empleado, tipo_licencia).data["id"]

    creado = cliente_supervisor.post(
        f"/api/v1/novedades/{nov}/adjuntos/",
        {"archivo": _archivo("certificado.pdf")},
        format="multipart",
    )

    assert creado.status_code == 201, creado.data
    assert cliente_supervisor.get(
        f"/api/v1/novedades/{nov}/adjuntos/"
    ).status_code == 403
    assert cliente_supervisor.get(creado.data["archivo_url"]).status_code == 403
    assert cliente_supervisor.delete(
        f"/api/v1/novedades/{nov}/adjuntos/{creado.data['id']}/"
    ).status_code == 403

    # El rol Empleado es acumulable, pero solo habilita evidencia del propio titular.
    from django.contrib.auth.models import Group

    supervisor.groups.add(Group.objects.get_or_create(name=roles.EMPLEADO)[0])
    assert cliente_supervisor.get(
        f"/api/v1/novedades/{nov}/adjuntos/"
    ).status_code == 404
    assert cliente_supervisor.get(creado.data["archivo_url"]).status_code == 404


def test_no_se_adjunta_cualquier_cosa(cliente_rrhh, empleado, tipo_licencia, media_temporal):
    nov = _alta(cliente_rrhh, empleado, tipo_licencia).data["id"]
    resp = cliente_rrhh.post(
        f"/api/v1/novedades/{nov}/adjuntos/",
        {"archivo": _archivo("virus.exe", b"MZ")},
        format="multipart",
    )
    assert resp.status_code == 400
    assert "exe" in str(resp.data)
