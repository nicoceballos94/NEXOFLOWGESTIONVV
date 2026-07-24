"""Tests de la app empleados: alta con relación, R1, baja lógica (R10), scoping y documentos."""
import pytest

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.empleados.models import Empleado, EstadoRelacion, RelacionLaboral
from apps.organizacion.models import Empresa, Puesto, Sector

pytestmark = pytest.mark.django_db


@pytest.fixture
def empresa():
    sector = Sector.objects.create(nombre="Operaciones")
    puesto = Puesto.objects.create(nombre="Chofer", sector=sector)
    empresa = Empresa.objects.create(nombre="VIAL VICTORIA")
    empresa._sector_prueba = sector
    empresa._puesto_prueba = puesto
    return empresa


def _payload_alta(empresa, **over):
    # Sin `legajo`: lo asigna el backend (ver test_el_legajo_lo_asigna_el_backend).
    sector = getattr(empresa, "_sector_prueba", Sector.objects.filter(activo=True).first())
    puesto = getattr(
        empresa,
        "_puesto_prueba",
        Puesto.objects.filter(activo=True, sector=sector).first(),
    )
    datos = {
        "dni": "30111222",
        "nombre": "Juan",
        "apellido": "Pérez",
        "relacion": {
            "empresa": empresa.id,
            "sector": sector.id,
            "puesto": puesto.id,
            "fecha_ingreso": "2024-01-10",
        },
    }
    datos.update(over)
    return datos


def test_rrhh_da_alta_empleado_con_relacion_activa(cliente_rrhh, empresa):
    resp = cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    assert resp.status_code == 201, resp.data
    empleado = Empleado.objects.get(legajo="0001")
    assert empleado.relaciones.filter(estado=EstadoRelacion.ACTIVA).count() == 1
    assert resp.data["activo"] is True


def test_alta_rechaza_fecha_de_nacimiento_futura(cliente_rrhh, empresa):
    respuesta = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa, fecha_nacimiento="2099-01-01"),
        format="json",
    )

    assert respuesta.status_code == 400
    assert "fecha_nacimiento" in respuesta.data["campos"]


def test_alta_rechaza_vencimiento_de_contrato_anterior_al_ingreso(
    cliente_rrhh,
    empresa,
):
    payload = _payload_alta(empresa)
    payload["relacion"]["fecha_vencimiento_contrato"] = "2024-01-09"

    respuesta = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")

    assert respuesta.status_code == 400
    assert "fecha_vencimiento_contrato" in respuesta.data["campos"]["relacion"]


def test_filtro_fk_invalido_devuelve_400_y_no_un_error_500(cliente_rrhh):
    respuesta = cliente_rrhh.get("/api/v1/empleados/?empresa=abc")
    assert respuesta.status_code == 400
    assert "empresa" in respuesta.data["campos"]


def test_rrhh_actualiza_puesto_y_sector_sin_falsear_baja_reingreso(
    cliente_rrhh, empresa
):
    alta = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa),
        format="json",
    )
    empleado = Empleado.objects.get(pk=alta.data["id"])
    relacion = empleado.relacion_activa
    sector_nuevo = Sector.objects.create(nombre="Logística")
    puesto_nuevo = Puesto.objects.create(
        nombre="Chofer avanzado",
        sector=sector_nuevo,
    )

    respuesta = cliente_rrhh.patch(
        (
            f"/api/v1/empleados/{empleado.id}/relaciones/"
            f"{relacion.id}/"
        ),
        {
            "sector": sector_nuevo.id,
            "puesto": puesto_nuevo.id,
            "tipo_contrato": "PLAZO_FIJO",
        },
        format="json",
    )

    assert respuesta.status_code == 200, respuesta.data
    relacion.refresh_from_db()
    assert relacion.sector_id == sector_nuevo.id
    assert relacion.puesto_id == puesto_nuevo.id
    assert relacion.tipo_contrato == "PLAZO_FIJO"
    assert relacion.fecha_ingreso.isoformat() == "2024-01-10"
    assert empleado.relaciones.count() == 1
    evento = RegistroAuditoria.objects.get(
        accion=Accion.RELACION_ACTUALIZADA,
        objeto_id=relacion.id,
    )
    assert set(evento.valores_antes) == {"sector", "puesto", "tipo_contrato"}
    assert set(evento.valores_despues) == {"sector", "puesto", "tipo_contrato"}


def test_sector_no_se_reescribe_si_el_checklist_ya_fotografio_el_ingreso(
    cliente_rrhh,
    empresa,
):
    from apps.onboarding.models import ProcesoEmpleado, TipoProceso

    alta = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa),
        format="json",
    )
    empleado = Empleado.objects.get(pk=alta.data["id"])
    relacion = empleado.relacion_activa
    ProcesoEmpleado.objects.create(
        relacion_laboral=relacion,
        tipo_proceso=TipoProceso.INGRESO,
    )
    sector_nuevo = Sector.objects.create(nombre="Logística")
    puesto_nuevo = Puesto.objects.create(nombre="Operador", sector=sector_nuevo)

    respuesta = cliente_rrhh.patch(
        f"/api/v1/empleados/{empleado.id}/relaciones/{relacion.id}/",
        {"sector": sector_nuevo.id, "puesto": puesto_nuevo.id},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "sector" in respuesta.data["campos"]
    relacion.refresh_from_db()
    assert relacion.sector_id == empresa._sector_prueba.id


def test_promocion_en_el_mismo_sector_sigue_permitida_con_checklist(
    cliente_rrhh,
    empresa,
):
    from apps.onboarding.models import ProcesoEmpleado, TipoProceso

    alta = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa),
        format="json",
    )
    empleado = Empleado.objects.get(pk=alta.data["id"])
    relacion = empleado.relacion_activa
    ProcesoEmpleado.objects.create(
        relacion_laboral=relacion,
        tipo_proceso=TipoProceso.INGRESO,
    )
    puesto_nuevo = Puesto.objects.create(
        nombre="Chofer avanzado",
        sector=empresa._sector_prueba,
    )

    respuesta = cliente_rrhh.patch(
        f"/api/v1/empleados/{empleado.id}/relaciones/{relacion.id}/",
        {"puesto": puesto_nuevo.id},
        format="json",
    )

    assert respuesta.status_code == 200, respuesta.data
    relacion.refresh_from_db()
    assert relacion.puesto_id == puesto_nuevo.id


def test_actualizar_relacion_rechaza_puesto_de_otro_sector(cliente_rrhh, empresa):
    alta = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa),
        format="json",
    )
    empleado = Empleado.objects.get(pk=alta.data["id"])
    relacion = empleado.relacion_activa
    otro_sector = Sector.objects.create(nombre="Administración")
    puesto_ajeno = Puesto.objects.create(nombre="Analista", sector=otro_sector)

    respuesta = cliente_rrhh.patch(
        (
            f"/api/v1/empleados/{empleado.id}/relaciones/"
            f"{relacion.id}/"
        ),
        {"puesto": puesto_ajeno.id},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "puesto" in respuesta.data["campos"]
    relacion.refresh_from_db()
    assert relacion.puesto_id == empresa._puesto_prueba.id
    assert not RegistroAuditoria.objects.filter(
        accion=Accion.RELACION_ACTUALIZADA
    ).exists()


def test_edicion_combinada_guarda_persona_y_asignacion_atomicamente(
    cliente_rrhh, empresa
):
    alta = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa),
        format="json",
    )
    empleado = Empleado.objects.get(pk=alta.data["id"])
    nuevo_puesto = Puesto.objects.create(
        nombre="Chofer avanzado",
        sector=empresa._sector_prueba,
    )

    respuesta = cliente_rrhh.patch(
        f"/api/v1/empleados/{empleado.id}/ficha/",
        {
            "empleado": {"telefono": "11-5555-0000"},
            "relacion": {
                "sector": empresa._sector_prueba.id,
                "puesto": nuevo_puesto.id,
                "jornada_legal": "COMPLETA_8H",
            },
        },
        format="json",
    )

    assert respuesta.status_code == 200, respuesta.data
    empleado.refresh_from_db()
    relacion = empleado.relacion_activa
    assert empleado.telefono == "11-5555-0000"
    assert relacion.puesto_id == nuevo_puesto.id
    assert relacion.jornada_legal == "COMPLETA_8H"
    assert RegistroAuditoria.objects.filter(
        accion=Accion.EMPLEADO_ACTUALIZADO,
        objeto_id=empleado.id,
    ).exists()
    assert RegistroAuditoria.objects.filter(
        accion=Accion.RELACION_ACTUALIZADA,
        objeto_id=relacion.id,
    ).exists()


def test_campos_unicos_opcionales_vacios_se_normalizan_a_null(
    cliente_rrhh, empresa
):
    primero = _payload_alta(
        empresa,
        cuil="",
        id_huella="   ",
    )
    segundo = _payload_alta(
        empresa,
        dni="30999888",
        cuil="   ",
        id_huella="",
    )

    alta_primero = cliente_rrhh.post(
        "/api/v1/empleados/",
        primero,
        format="json",
    )
    alta_segundo = cliente_rrhh.post(
        "/api/v1/empleados/",
        segundo,
        format="json",
    )

    assert alta_primero.status_code == 201, alta_primero.data
    assert alta_segundo.status_code == 201, alta_segundo.data
    assert Empleado.objects.filter(cuil__isnull=True).count() == 2
    assert Empleado.objects.filter(id_huella__isnull=True).count() == 2


def test_identificadores_se_normalizan_antes_de_validar_unicidad(
    cliente_rrhh, empresa
):
    primera = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(
            empresa,
            dni="30.111.222",
            cuil="20-30111222-3",
            id_huella=" huella-77 ",
        ),
        format="json",
    )
    duplicada = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa, dni="30111222"),
        format="json",
    )

    assert primera.status_code == 201, primera.data
    empleado = Empleado.objects.get(pk=primera.data["id"])
    assert empleado.dni == "30111222"
    assert empleado.cuil == "20301112223"
    assert empleado.id_huella == "HUELLA-77"
    assert duplicada.status_code == 400
    assert "dni" in duplicada.data["campos"]


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


@pytest.mark.parametrize("campo", ["sector", "puesto"])
def test_alta_exige_sector_y_puesto_catalogados(cliente_rrhh, empresa, campo):
    payload = _payload_alta(empresa)
    payload["relacion"].pop(campo)

    resp = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")

    assert resp.status_code == 400
    assert campo in str(resp.data)
    assert not Empleado.objects.filter(dni="30111222").exists()


def test_alta_no_crea_un_puesto_desde_texto_libre(cliente_rrhh, empresa):
    cantidad_inicial = Puesto.objects.count()
    payload = _payload_alta(empresa)
    payload["relacion"]["puesto"] = "Chofer inventado"

    resp = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")

    assert resp.status_code == 400
    assert Puesto.objects.count() == cantidad_inicial
    assert not Empleado.objects.filter(dni="30111222").exists()


def test_alta_rechaza_puesto_que_no_pertenece_al_sector(cliente_rrhh, empresa):
    otro_sector = Sector.objects.create(nombre="Taller")
    otro_puesto = Puesto.objects.create(nombre="Mecánico", sector=otro_sector)
    payload = _payload_alta(empresa)
    payload["relacion"]["puesto"] = otro_puesto.id

    resp = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")

    assert resp.status_code == 400
    assert "puesto" in str(resp.data)


def test_supervisor_asignado_debe_tener_el_rol(
    cliente_rrhh, empresa, crear_usuario
):
    from common import roles

    usuario_rrhh = crear_usuario(username="no-supervisor", rol=roles.RRHH)
    payload = _payload_alta(empresa)
    payload["relacion"]["supervisor"] = usuario_rrhh.id

    resp = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")

    assert resp.status_code == 400
    assert "supervisor" in str(resp.data)


def test_rrhh_asigna_reasigna_y_quita_supervisor_con_auditoria(
    cliente_rrhh, empresa, crear_usuario
):
    from common import roles

    alta = cliente_rrhh.post(
        "/api/v1/empleados/", _payload_alta(empresa), format="json"
    )
    empleado = Empleado.objects.get(pk=alta.data["id"])
    relacion = empleado.relacion_activa
    primero = crear_usuario(username="supervisor-uno", rol=roles.SUPERVISOR)
    segundo = crear_usuario(username="supervisor-dos", rol=roles.SUPERVISOR)
    url = (
        f"/api/v1/empleados/{empleado.id}/relaciones/"
        f"{relacion.id}/supervisor/"
    )

    asignada = cliente_rrhh.patch(
        url, {"supervisor": primero.id}, format="json"
    )
    reasignada = cliente_rrhh.patch(
        url, {"supervisor": segundo.id}, format="json"
    )
    quitada = cliente_rrhh.patch(url, {"supervisor": None}, format="json")

    assert asignada.status_code == 200, asignada.data
    assert asignada.data["supervisor"] == primero.id
    assert reasignada.status_code == 200, reasignada.data
    assert reasignada.data["supervisor"] == segundo.id
    assert quitada.status_code == 200, quitada.data
    assert quitada.data["supervisor"] is None
    relacion.refresh_from_db()
    assert relacion.supervisor_id is None
    eventos = RegistroAuditoria.objects.filter(
        accion=Accion.RELACION_SUPERVISOR_CAMBIADO,
        objeto_id=relacion.id,
    ).order_by("id")
    assert eventos.count() == 3
    assert all(evento.empleado_id == empleado.id for evento in eventos)
    assert eventos[0].valores_despues["supervisor"] == "supervisor-uno"
    assert eventos[1].valores_despues["supervisor"] == "supervisor-dos"
    assert eventos[2].valores_despues["supervisor"] is None


def test_repetir_el_mismo_supervisor_es_idempotente(
    cliente_rrhh, empresa, crear_usuario
):
    from common import roles

    supervisor = crear_usuario(username="supervisor-idem", rol=roles.SUPERVISOR)
    payload = _payload_alta(empresa)
    payload["relacion"]["supervisor"] = supervisor.id
    alta = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")
    empleado = Empleado.objects.get(pk=alta.data["id"])
    relacion = empleado.relacion_activa
    url = (
        f"/api/v1/empleados/{empleado.id}/relaciones/"
        f"{relacion.id}/supervisor/"
    )

    resp = cliente_rrhh.patch(
        url, {"supervisor": supervisor.id}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert not RegistroAuditoria.objects.filter(
        accion=Accion.RELACION_SUPERVISOR_CAMBIADO,
        objeto_id=relacion.id,
    ).exists()


@pytest.mark.parametrize("caso", ["sin_rol", "inactivo", "servicio"])
def test_no_asigna_identidades_no_aptas_como_supervisor(
    cliente_rrhh, empresa, crear_usuario, caso
):
    from common import roles

    alta = cliente_rrhh.post(
        "/api/v1/empleados/", _payload_alta(empresa), format="json"
    )
    empleado = Empleado.objects.get(pk=alta.data["id"])
    relacion = empleado.relacion_activa
    if caso == "sin_rol":
        candidato = crear_usuario(username="candidato-sin-rol", rol=roles.RRHH)
    elif caso == "servicio":
        candidato = crear_usuario(
            username="candidato-servicio",
            rol=roles.SERVICIO,
        )
    else:
        candidato = crear_usuario(
            username=f"candidato-{caso}",
            rol=roles.SUPERVISOR,
            is_active=caso != "inactivo",
        )
    url = (
        f"/api/v1/empleados/{empleado.id}/relaciones/"
        f"{relacion.id}/supervisor/"
    )

    resp = cliente_rrhh.patch(
        url, {"supervisor": candidato.id}, format="json"
    )

    assert resp.status_code == 400, resp.data
    assert "supervisor" in resp.data["campos"]
    relacion.refresh_from_db()
    assert relacion.supervisor_id is None


def test_no_cambia_supervisor_de_relacion_finalizada(
    cliente_rrhh, empresa, crear_usuario
):
    from common import roles

    alta = cliente_rrhh.post(
        "/api/v1/empleados/", _payload_alta(empresa), format="json"
    )
    empleado = Empleado.objects.get(pk=alta.data["id"])
    relacion = empleado.relacion_activa
    cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/relaciones/{relacion.id}/finalizar/",
        {"fecha_egreso": "2025-03-01", "motivo_egreso": "RENUNCIA"},
        format="json",
    )
    supervisor = crear_usuario(username="supervisor-tarde", rol=roles.SUPERVISOR)

    resp = cliente_rrhh.patch(
        (
            f"/api/v1/empleados/{empleado.id}/relaciones/"
            f"{relacion.id}/supervisor/"
        ),
        {"supervisor": supervisor.id},
        format="json",
    )

    assert resp.status_code == 400, resp.data
    assert "estado" in resp.data["campos"]


def test_empleado_no_puede_reasignar_supervisor(
    cliente_rrhh, empresa, crear_usuario
):
    from rest_framework.test import APIClient

    from common import roles

    alta = cliente_rrhh.post(
        "/api/v1/empleados/", _payload_alta(empresa), format="json"
    )
    empleado = Empleado.objects.get(pk=alta.data["id"])
    relacion = empleado.relacion_activa
    supervisor = crear_usuario(username="supervisor-protegido", rol=roles.SUPERVISOR)
    cliente_empleado = APIClient()
    cliente_empleado.force_authenticate(
        crear_usuario(username="empleado-sin-permiso", rol=roles.EMPLEADO)
    )

    resp = cliente_empleado.patch(
        (
            f"/api/v1/empleados/{empleado.id}/relaciones/"
            f"{relacion.id}/supervisor/"
        ),
        {"supervisor": supervisor.id},
        format="json",
    )

    assert resp.status_code == 403
    relacion.refresh_from_db()
    assert relacion.supervisor_id is None


@pytest.mark.parametrize("catalogo", ["empresa", "sector", "puesto"])
def test_alta_rechaza_catalogos_inactivos(cliente_rrhh, empresa, catalogo):
    payload = _payload_alta(empresa)
    if catalogo == "empresa":
        empresa.activa = False
        empresa.save(update_fields=["activa"])
    elif catalogo == "sector":
        empresa._sector_prueba.activo = False
        empresa._sector_prueba.save(update_fields=["activo"])
    else:
        empresa._puesto_prueba.activo = False
        empresa._puesto_prueba.save(update_fields=["activo"])

    resp = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")

    assert resp.status_code == 400
    assert catalogo in str(resp.data)
    assert not Empleado.objects.filter(dni="30111222").exists()


def test_no_dos_relaciones_activas_en_el_grupo(cliente_rrhh, empresa):
    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(legajo="0001")
    # intentar una segunda relación ACTIVA en la misma empresa (R1)
    from apps.empleados import services

    with pytest.raises(Exception):
        services.crear_relacion_laboral(
            actor=None,
            empleado=empleado,
            empresa=Empresa.objects.create(nombre="OTRA EMPRESA"),
            sector=empresa._sector_prueba,
            puesto=empresa._puesto_prueba,
            fecha_ingreso="2024-05-01",
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
        {
            "empresa": empresa.id,
            "sector": empresa._sector_prueba.id,
            "puesto": empresa._puesto_prueba.id,
            "fecha_ingreso": "2025-06-01",
        },
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


# ---------- PII por rol (A3) ----------
# El scope dice a QUIÉNES ve cada rol; esto dice CUÁNTO ve de cada uno. El Supervisor ve
# solo sus asignados, y eso tampoco incluye el DNI ni la dirección de cada persona.
_PII = (
    "dni",
    "cuil",
    "fecha_nacimiento",
    "telefono",
    "direccion",
    "contacto_emergencia",
    "obra_social",
    "art",
    "id_huella",
    "observaciones",
)


@pytest.fixture
def _alta_con_pii(cliente_rrhh, empresa):
    """Un empleado con todos los campos PII cargados, para que ocultarlos se note."""
    resp = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(
            empresa,
            cuil="20301112223",
            fecha_nacimiento="1985-06-15",
            telefono="3435551234",
            direccion="Belgrano 742",
            contacto_emergencia="María Pérez 3435559999",
            obra_social="OSECAC",
            art="Prevención",
            id_huella="H-77",
            observaciones="Cambió de turno en marzo",
        ),
        format="json",
    )
    assert resp.status_code == 201, resp.data
    return Empleado.objects.get(legajo="0001")


def _cliente_con_rol(crear_usuario, rol, username):
    from rest_framework.test import APIClient

    cliente = APIClient()
    cliente.force_authenticate(crear_usuario(username=username, rol=rol))
    return cliente


def test_supervisor_ve_la_dotacion_pero_no_el_pii(_alta_con_pii, crear_usuario):
    from common import roles

    supervisor = crear_usuario(username="supervisor", rol=roles.SUPERVISOR)
    relacion = _alta_con_pii.relacion_activa
    relacion.supervisor = supervisor
    relacion.save(update_fields=["supervisor"])
    from rest_framework.test import APIClient

    cliente = APIClient()
    cliente.force_authenticate(supervisor)

    lista = cliente.get("/api/v1/empleados/")
    assert lista.status_code == 200
    assert lista.data["count"] == 1
    ficha = lista.data["results"][0]
    for campo in _PII:
        assert campo not in ficha, f"{campo} se filtró al Supervisor en la lista"
    assert "email" not in ficha
    # ...y lo que necesita para operar sigue estando.
    assert ficha["legajo"] == "0001"
    assert ficha["nombre_completo"] == "Pérez, Juan"
    assert ficha["relaciones"][0]["fecha_ingreso"] == "2024-01-10"

    detalle = cliente.get(f"/api/v1/empleados/{_alta_con_pii.id}/")
    assert detalle.status_code == 200
    for campo in _PII:
        assert campo not in detalle.data, f"{campo} se filtró al Supervisor en el detalle"

    # Ocultarlo en la respuesta no alcanza: si q consultara DNI, count permitiría
    # reconstruirlo carácter por carácter.
    por_dni = cliente.get("/api/v1/empleados/", {"q": "301112"})
    assert por_dni.status_code == 200
    assert por_dni.data["count"] == 0
    por_nombre = cliente.get("/api/v1/empleados/", {"q": "Juan"})
    assert por_nombre.data["count"] == 1


def test_rol_mixto_supervisor_empleado_ve_equipo_y_tambien_su_ficha(
    _alta_con_pii, empresa, crear_usuario
):
    from django.contrib.auth.models import Group
    from rest_framework.test import APIClient

    from common import roles

    usuario = crear_usuario(username="supervisor-empleado", rol=roles.SUPERVISOR)
    usuario.groups.add(Group.objects.get_or_create(name=roles.EMPLEADO)[0])
    relacion_equipo = _alta_con_pii.relacion_activa
    relacion_equipo.supervisor = usuario
    relacion_equipo.save(update_fields=["supervisor"])

    propio = Empleado.objects.create(
        legajo="0900",
        dni="33444555",
        nombre="Sofía",
        apellido="Jefa",
        email="sofia@example.com",
        usuario=usuario,
    )
    RelacionLaboral.objects.create(
        empleado=propio,
        empresa=empresa,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        fecha_ingreso="2024-02-01",
    )
    cliente = APIClient()
    cliente.force_authenticate(usuario)

    lista = cliente.get("/api/v1/empleados/")
    assert lista.status_code == 200
    assert {fila["id"] for fila in lista.data["results"]} == {
        propio.id,
        _alta_con_pii.id,
    }

    ficha_propia = cliente.get(f"/api/v1/empleados/{propio.id}/")
    assert ficha_propia.data["dni"] == "33444555"
    assert ficha_propia.data["email"] == "sofia@example.com"
    assert len(ficha_propia.data["relaciones"]) == 1
    ficha_equipo = cliente.get(f"/api/v1/empleados/{_alta_con_pii.id}/")
    assert "dni" not in ficha_equipo.data


def test_supervisor_deja_de_ver_al_empleado_al_finalizar_la_asignacion(
    _alta_con_pii, crear_usuario, cliente_rrhh
):
    from rest_framework.test import APIClient

    from common import roles

    supervisor = crear_usuario(username="supervisor-baja", rol=roles.SUPERVISOR)
    relacion = _alta_con_pii.relacion_activa
    relacion.supervisor = supervisor
    relacion.save(update_fields=["supervisor"])
    cliente = APIClient()
    cliente.force_authenticate(supervisor)
    assert cliente.get("/api/v1/empleados/").data["count"] == 1

    baja = cliente_rrhh.post(
        f"/api/v1/empleados/{_alta_con_pii.id}/relaciones/{relacion.id}/finalizar/",
        {"fecha_egreso": "2025-03-01", "motivo_egreso": "RENUNCIA"},
        format="json",
    )
    assert baja.status_code == 200, baja.data

    lista = cliente.get("/api/v1/empleados/")
    assert lista.status_code == 200
    assert lista.data["count"] == 0
    assert cliente.get(f"/api/v1/empleados/{_alta_con_pii.id}/").status_code == 404


def test_supervisor_no_recibe_relaciones_historicas_de_otros_responsables(
    cliente_rrhh, empresa, crear_usuario
):
    from rest_framework.test import APIClient

    from common import roles

    anterior = crear_usuario(username="supervisor-anterior", rol=roles.SUPERVISOR)
    actual = crear_usuario(username="supervisor-actual", rol=roles.SUPERVISOR)
    payload = _payload_alta(empresa)
    payload["relacion"]["supervisor"] = anterior.id
    alta = cliente_rrhh.post("/api/v1/empleados/", payload, format="json")
    assert alta.status_code == 201, alta.data
    empleado = Empleado.objects.get(pk=alta.data["id"])
    vieja = empleado.relacion_activa
    cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/relaciones/{vieja.id}/finalizar/",
        {"fecha_egreso": "2024-12-31", "motivo_egreso": "RENUNCIA"},
        format="json",
    )
    nueva = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/relaciones/",
        {
            "empresa": empresa.id,
            "sector": empresa._sector_prueba.id,
            "puesto": empresa._puesto_prueba.id,
            "supervisor": actual.id,
            "fecha_ingreso": "2025-01-01",
        },
        format="json",
    )
    assert nueva.status_code == 201, nueva.data

    cliente = APIClient()
    cliente.force_authenticate(actual)
    detalle = cliente.get(f"/api/v1/empleados/{empleado.id}/")
    assert detalle.status_code == 200
    assert [relacion["id"] for relacion in detalle.data["relaciones"]] == [
        nueva.data["id"]
    ]


def test_el_listado_de_rrhh_es_resumen_y_no_elude_la_auditoria(
    _alta_con_pii, cliente_rrhh
):
    resp = cliente_rrhh.get("/api/v1/empleados/")

    assert resp.status_code == 200
    fila = next(
        empleado
        for empleado in resp.data["results"]
        if empleado["id"] == _alta_con_pii.id
    )
    for campo in _PII:
        assert campo not in fila
    assert fila["nombre_completo"] == _alta_con_pii.nombre_completo
    assert fila["relaciones"]
    assert not RegistroAuditoria.objects.filter(
        accion=Accion.EMPLEADO_CONSULTADO,
        objeto_id=_alta_con_pii.id,
    ).exists()


def test_rrhh_sigue_viendo_el_pii_completo(_alta_con_pii, cliente_rrhh):
    resp = cliente_rrhh.get(f"/api/v1/empleados/{_alta_con_pii.id}/")
    assert resp.status_code == 200
    for campo in _PII:
        assert campo in resp.data, f"a RRHH le falta {campo}"
    assert resp.data["dni"] == "30111222"
    assert resp.data["direccion"] == "Belgrano 742"


def test_consultar_detalle_sensible_deja_evento_de_auditoria(
    _alta_con_pii, cliente_rrhh
):
    existentes = RegistroAuditoria.objects.filter(
        accion=Accion.EMPLEADO_CONSULTADO,
        objeto_id=_alta_con_pii.id,
    ).count()

    resp = cliente_rrhh.get(f"/api/v1/empleados/{_alta_con_pii.id}/")

    assert resp.status_code == 200
    evento = RegistroAuditoria.objects.get(
        accion=Accion.EMPLEADO_CONSULTADO,
        objeto_id=_alta_con_pii.id,
    )
    assert existentes == 0
    assert evento.entidad == "Empleado"
    assert evento.empleado_id == _alta_con_pii.id
    assert evento.usuario_nombre == "rrhh"
    assert evento.valores_antes == {}
    assert evento.valores_despues == {}


def test_el_empleado_ve_el_pii_de_su_propia_ficha(_alta_con_pii, crear_usuario, api_client):
    """Ocultarle a alguien su propio DNI no protege a nadie y rompe la autoconsulta."""
    from common import roles

    usuario = crear_usuario(username="juan-titular", rol=roles.EMPLEADO)
    _alta_con_pii.usuario = usuario
    _alta_con_pii.save()
    api_client.force_authenticate(usuario)

    resp = api_client.get(f"/api/v1/empleados/{_alta_con_pii.id}/")
    assert resp.status_code == 200
    assert resp.data["dni"] == "30111222"
    assert resp.data["contacto_emergencia"] == "María Pérez 3435559999"


def test_el_pii_tambien_se_recorta_al_crear_y_editar(_alta_con_pii, cliente_rrhh):
    """La respuesta de POST/PATCH pasa por el mismo serializer: si el recorte viviera solo
    en `list`, el alta devolvería la ficha entera por la puerta de atrás. Acá el actor es
    RRHH (nadie más puede escribir), así que lo que se verifica es que el contexto llegue
    —sin él el serializer falla cerrado y RRHH vería su propia alta sin el DNI que acaba
    de cargar."""
    from apps.organizacion.models import Empresa

    alta = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(Empresa.objects.first(), dni="30777888", telefono="3435550000"),
        format="json",
    )
    assert alta.status_code == 201, alta.data
    assert alta.data["dni"] == "30777888"

    patch = cliente_rrhh.patch(
        f"/api/v1/empleados/{_alta_con_pii.id}/", {"telefono": "3435557777"}, format="json"
    )
    assert patch.status_code == 200, patch.data
    assert patch.data["telefono"] == "3435557777"


def test_sin_request_en_contexto_el_serializer_falla_cerrado(_alta_con_pii):
    """Un llamador que se olvide el contexto ve campos faltantes, no PII de más."""
    from apps.empleados.api.serializers import EmpleadoSerializer

    datos = EmpleadoSerializer(_alta_con_pii).data
    for campo in _PII:
        assert campo not in datos


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
        empleado=empleado,
        empresa=otra,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        fecha_ingreso="2020-01-01",
        fecha_egreso="2023-12-31",
        motivo_egreso="RENUNCIA",
        estado=EstadoRelacion.FINALIZADA,
    )
    RelacionLaboral.objects.create(  # activa en `empresa`
        empleado=empleado,
        empresa=empresa,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        fecha_ingreso="2024-01-01",
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


def test_filtro_de_supervisor_no_revela_una_empresa_historica_ajena(
    empresa,
    crear_usuario,
):
    from rest_framework.test import APIClient

    from common import roles

    supervisor = crear_usuario(username="super-filtros", rol=roles.SUPERVISOR)
    historica = Empresa.objects.create(nombre="EMPRESA HISTÓRICA")
    empleado = Empleado.objects.create(
        legajo="0200",
        dni="30888777",
        nombre="Con",
        apellido="Historia",
    )
    RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=historica,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        fecha_ingreso="2020-01-01",
        fecha_egreso="2022-12-31",
        motivo_egreso="RENUNCIA",
        estado=EstadoRelacion.FINALIZADA,
    )
    RelacionLaboral.objects.create(
        empleado=empleado,
        empresa=empresa,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        supervisor=supervisor,
        fecha_ingreso="2023-01-01",
        estado=EstadoRelacion.ACTIVA,
    )
    cliente = APIClient()
    cliente.force_authenticate(supervisor)

    oculta = cliente.get(f"/api/v1/empleados/?empresa={historica.id}")
    visible = cliente.get(f"/api/v1/empleados/?empresa={empresa.id}")

    assert oculta.status_code == 200
    assert oculta.data["count"] == 0
    assert [fila["id"] for fila in visible.data["results"]] == [empleado.id]


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
    assert creado.data["relacion_laboral"] == empleado.relacion_activa.id
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


def test_reingreso_abre_una_nueva_carpeta_documental(cliente_rrhh, empresa):
    """El mismo tipo vuelve a ser exigible: la unicidad pertenece a cada relación."""
    from apps.empleados.models import DocumentoEmpleado, TipoDocumento

    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(dni="30111222")
    primera_relacion = empleado.relacion_activa
    tipo = TipoDocumento.objects.create(nombre="Apto médico")
    primero = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id},
        format="json",
    )
    assert primero.status_code == 201, primero.data

    baja = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/relaciones/{primera_relacion.id}/finalizar/",
        {"fecha_egreso": "2024-12-31", "motivo_egreso": "RENUNCIA"},
        format="json",
    )
    assert baja.status_code == 200, baja.data
    reingreso = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/relaciones/",
        {
            "empresa": empresa.id,
            "sector": empresa._sector_prueba.id,
            "puesto": empresa._puesto_prueba.id,
            "fecha_ingreso": "2025-01-01",
        },
        format="json",
    )
    assert reingreso.status_code == 201, reingreso.data

    segundo = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id},
        format="json",
    )
    assert segundo.status_code == 201, segundo.data
    assert segundo.data["relacion_laboral"] == reingreso.data["id"]
    assert DocumentoEmpleado.objects.filter(
        empleado=empleado, tipo_documento=tipo
    ).count() == 2

    listado_actual = cliente_rrhh.get(
        f"/api/v1/empleados/{empleado.id}/documentos/"
    )
    assert [documento["id"] for documento in listado_actual.data] == [
        segundo.data["id"]
    ]
    listado_historico = cliente_rrhh.get(
        f"/api/v1/empleados/{empleado.id}/documentos/?relacion={primera_relacion.id}"
    )
    assert [documento["id"] for documento in listado_historico.data] == [
        primero.data["id"]
    ]
    assert (
        cliente_rrhh.patch(
            f"/api/v1/empleados/{empleado.id}/documentos/{primero.data['id']}/",
            {"numero": "NO-DEBE-CAMBIAR"},
            format="json",
        ).status_code
        == 404
    )
    assert (
        cliente_rrhh.delete(
            f"/api/v1/empleados/{empleado.id}/documentos/{primero.data['id']}/"
        ).status_code
        == 404
    )


def test_documento_requiere_una_relacion_activa(cliente_rrhh, empresa):
    from apps.empleados.models import TipoDocumento

    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(dni="30111222")
    relacion = empleado.relacion_activa
    cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/relaciones/{relacion.id}/finalizar/",
        {"fecha_egreso": "2024-12-31", "motivo_egreso": "RENUNCIA"},
        format="json",
    )
    tipo = TipoDocumento.objects.create(nombre="Apto médico")

    respuesta = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "relacion_laboral" in str(respuesta.data)


def test_documento_rechaza_tipo_inactivo(cliente_rrhh, empresa):
    from apps.empleados.models import TipoDocumento

    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    empleado = Empleado.objects.get(dni="30111222")
    tipo = TipoDocumento.objects.create(nombre="Legado", activo=False)

    respuesta = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id},
        format="json",
    )

    assert respuesta.status_code == 400
    assert "tipo_documento" in str(respuesta.data)


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


# ---------- Documentos: archivo de respaldo (CU-06) ----------
@pytest.fixture
def media_temporal(settings, tmp_path):
    """MEDIA_ROOT propio por test: los archivos subidos no ensucian el repo ni se pisan."""
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _archivo(nombre="apto.pdf", contenido=b"%PDF-1.4 escaneo", tipo="application/pdf"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(nombre, contenido, content_type=tipo)


def _empleado_con_tipo(cliente_rrhh, empresa):
    from apps.empleados.models import TipoDocumento

    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    return Empleado.objects.get(dni="30111222"), TipoDocumento.objects.create(nombre="Apto médico")


def test_fallo_posterior_no_deja_documento_nuevo_huerfano(
    cliente_rrhh, empresa, media_temporal, monkeypatch
):
    from apps.empleados import services

    empleado, tipo = _empleado_con_tipo(cliente_rrhh, empresa)

    def fallar_auditoria(**_kwargs):
        raise RuntimeError("auditoría no disponible")

    monkeypatch.setattr(services, "registrar_evento", fallar_auditoria)
    with pytest.raises(RuntimeError):
        services.crear_documento(
            actor=None,
            empleado=empleado,
            tipo_documento=tipo,
            archivo=_archivo("huerfano.pdf"),
        )

    assert not [ruta for ruta in media_temporal.rglob("*") if ruta.is_file()]


def test_fallo_posterior_no_deja_foto_nueva_huerfana(
    cliente_rrhh, empresa, media_temporal, monkeypatch
):
    from apps.empleados import services

    empleado = _empleado(cliente_rrhh, empresa)

    def fallar_auditoria(**_kwargs):
        raise RuntimeError("auditoría no disponible")

    monkeypatch.setattr(services, "registrar_evento", fallar_auditoria)
    with pytest.raises(RuntimeError):
        services.guardar_foto_empleado(
            actor=None,
            empleado=empleado,
            foto=_imagen("huerfana.png"),
        )

    assert not [ruta for ruta in media_temporal.rglob("*") if ruta.is_file()]


def test_documento_con_archivo_se_sube_y_se_descarga(cliente_rrhh, empresa, media_temporal):
    from apps.empleados.models import DocumentoEmpleado

    empleado, tipo = _empleado_con_tipo(cliente_rrhh, empresa)
    creado = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id, "numero": "AM-1", "archivo": _archivo()},
        format="multipart",
    )
    assert creado.status_code == 201, creado.data
    assert creado.data["tiene_archivo"] is True

    doc = DocumentoEmpleado.objects.get(pk=creado.data["id"])
    # El nombre original se descarta: en la ruta no puede quedar PII ni nada adivinable.
    assert "apto" not in doc.archivo.name
    assert doc.archivo.name.startswith(f"documentos/{empleado.id}/")

    resp = cliente_rrhh.get(creado.data["archivo_url"])
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content) == b"%PDF-1.4 escaneo"
    # Se baja como adjunto y con nombre legible, no como el UUID del disco.
    assert "attachment" in resp["Content-Disposition"]
    assert "apto-medico-perez-0001.pdf" in resp["Content-Disposition"]
    evento = RegistroAuditoria.objects.get(
        accion=Accion.DOCUMENTO_DESCARGADO,
        objeto_id=doc.id,
    )
    assert evento.entidad == "DocumentoEmpleado"
    assert evento.empleado_id == empleado.id
    assert evento.usuario_nombre == "rrhh"


def test_el_vencimiento_se_carga_sin_archivo(cliente_rrhh, empresa, media_temporal):
    """El archivo es opcional a propósito: el control de vencimientos (el objetivo de CU-06)
    funciona con la fecha sola, y el scan puede llegar después."""
    empleado, tipo = _empleado_con_tipo(cliente_rrhh, empresa)
    resp = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id, "fecha_vencimiento": "2027-01-01"},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["tiene_archivo"] is False
    assert resp.data["archivo_url"] is None


def test_renovar_borra_el_scan_viejo_del_disco(
    cliente_rrhh, empresa, media_temporal, django_capture_on_commit_callbacks
):
    """"No generar basura": el archivo reemplazado sale del disco. Django no lo hace solo, y
    el huérfano sería invisible (ninguna fila lo nombra) e imborrable a mano (se llama UUID)."""
    from apps.empleados.models import DocumentoEmpleado

    empleado, tipo = _empleado_con_tipo(cliente_rrhh, empresa)
    doc_id = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {
            "tipo_documento": tipo.id,
            "archivo": _archivo("viejo.pdf", b"%PDF-1.4 apto 2025"),
        },
        format="multipart",
    ).data["id"]
    ruta_vieja = media_temporal / DocumentoEmpleado.objects.get(pk=doc_id).archivo.name
    assert ruta_vieja.exists()

    with django_capture_on_commit_callbacks(execute=True):
        resp = cliente_rrhh.patch(
            f"/api/v1/empleados/{empleado.id}/documentos/{doc_id}/",
            {
                "archivo": _archivo("nuevo.pdf", b"%PDF-1.4 apto 2026"),
                "fecha_vencimiento": "2027-06-01",
            },
            format="multipart",
        )
    assert resp.status_code == 200, resp.data

    doc = DocumentoEmpleado.objects.get(pk=doc_id)
    assert not ruta_vieja.exists(), "el scan viejo quedó huérfano en MEDIA_ROOT"
    assert (media_temporal / doc.archivo.name).read_bytes() == b"%PDF-1.4 apto 2026"


def test_eliminar_documento_se_lleva_el_archivo(
    cliente_rrhh, empresa, media_temporal, django_capture_on_commit_callbacks
):
    """Borrar la fila y dejar el binario sería peor que no borrar: un dato de salud en el
    disco sin ninguna fila que diga de quién es."""
    from apps.empleados.models import DocumentoEmpleado

    empleado, tipo = _empleado_con_tipo(cliente_rrhh, empresa)
    doc_id = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/documentos/",
        {"tipo_documento": tipo.id, "archivo": _archivo()},
        format="multipart",
    ).data["id"]
    ruta = media_temporal / DocumentoEmpleado.objects.get(pk=doc_id).archivo.name

    with django_capture_on_commit_callbacks(execute=True):
        resp = cliente_rrhh.delete(f"/api/v1/empleados/{empleado.id}/documentos/{doc_id}/")
    assert resp.status_code == 204
    assert not ruta.exists()


def test_no_se_aceptan_formatos_ni_pesos_cualquiera(
    cliente_rrhh, empresa, media_temporal, settings
):
    empleado, tipo = _empleado_con_tipo(cliente_rrhh, empresa)
    url = f"/api/v1/empleados/{empleado.id}/documentos/"

    ejecutable = _archivo("virus.exe", b"MZ", "application/x-msdownload")
    resp = cliente_rrhh.post(
        url,
        {"tipo_documento": tipo.id, "archivo": ejecutable},
        format="multipart",
    )
    assert resp.status_code == 400
    assert "exe" in str(resp.data)

    settings.DOCUMENTO_MAX_BYTES = 1024
    resp = cliente_rrhh.post(
        url,
        {"tipo_documento": tipo.id, "archivo": _archivo("enorme.pdf", b"x" * 2048)},
        format="multipart",
    )
    assert resp.status_code == 400
    assert "MB" in str(resp.data)


def test_el_empleado_no_descarga_documentos_ajenos(
    cliente_rrhh, empresa, crear_usuario, media_temporal
):
    """A2: `documentos` resolvía el empleado sin pasar por el selector, así que cualquier
    autenticado leía los de cualquiera. Con archivos adjuntos eso era descargar el apto
    médico ajeno, no solo ver metadatos."""
    from rest_framework.test import APIClient

    from common import roles

    ajeno, tipo = _empleado_con_tipo(cliente_rrhh, empresa)
    creado = cliente_rrhh.post(
        f"/api/v1/empleados/{ajeno.id}/documentos/",
        {"tipo_documento": tipo.id, "archivo": _archivo()},
        format="multipart",
    )
    assert creado.status_code == 201, creado.data

    # Otro empleado, con su propia ficha y su propio usuario.
    propio = Empleado.objects.create(legajo="0500", dni="33444555", nombre="Otro", apellido="Tipo")
    usuario = crear_usuario(username="curioso", rol=roles.EMPLEADO)
    propio.usuario = usuario
    propio.save()
    cliente = APIClient()
    cliente.force_authenticate(usuario)

    assert cliente.get(f"/api/v1/empleados/{ajeno.id}/documentos/").status_code == 404
    assert cliente.get(creado.data["archivo_url"]).status_code == 404
    # Y sí ve lo suyo: el scope recorta, no bloquea.
    assert cliente.get(f"/api/v1/empleados/{propio.id}/documentos/").status_code == 200


def test_supervisor_no_lista_ni_descarga_legajos_documentales(
    cliente_rrhh, empresa, crear_usuario, media_temporal
):
    from rest_framework.test import APIClient

    from apps.empleados.models import TipoDocumento
    from common import roles

    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa, dni="30222333", nombre="Ana"),
        format="json",
    )
    asignado = Empleado.objects.get(dni="30111222")
    ajeno = Empleado.objects.get(dni="30222333")
    supervisor = crear_usuario(username="supervisor-docs", rol=roles.SUPERVISOR)
    relacion = asignado.relacion_activa
    relacion.supervisor = supervisor
    relacion.save(update_fields=["supervisor"])

    tipo = TipoDocumento.objects.create(nombre="Apto médico")
    doc_asignado = cliente_rrhh.post(
        f"/api/v1/empleados/{asignado.id}/documentos/",
        {"tipo_documento": tipo.id, "archivo": _archivo("asignado.pdf")},
        format="multipart",
    )
    doc_ajeno = cliente_rrhh.post(
        f"/api/v1/empleados/{ajeno.id}/documentos/",
        {"tipo_documento": tipo.id, "archivo": _archivo("ajeno.pdf")},
        format="multipart",
    )
    assert doc_asignado.status_code == 201, doc_asignado.data
    assert doc_ajeno.status_code == 201, doc_ajeno.data

    cliente = APIClient()
    cliente.force_authenticate(supervisor)
    lista = cliente.get("/api/v1/empleados/")
    assert [fila["id"] for fila in lista.data["results"]] == [asignado.id]
    assert cliente.get(
        f"/api/v1/empleados/{asignado.id}/documentos/"
    ).status_code == 403
    assert cliente.get(doc_asignado.data["archivo_url"]).status_code == 403
    # El permiso se rechaza antes de resolver el objeto, así tampoco funciona como oracle.
    assert cliente.get(f"/api/v1/empleados/{ajeno.id}/documentos/").status_code == 403
    assert cliente.get(doc_ajeno.data["archivo_url"]).status_code == 403

    # Un supervisor puede ser también empleado. Ese segundo rol solo abre su legajo
    # personal: nunca convierte el alcance operativo del equipo en alcance médico.
    from django.contrib.auth.models import Group

    supervisor.groups.add(Group.objects.get_or_create(name=roles.EMPLEADO)[0])
    assert cliente.get(
        f"/api/v1/empleados/{asignado.id}/documentos/"
    ).status_code == 404
    assert cliente.get(doc_asignado.data["archivo_url"]).status_code == 404


# ---------- Foto de perfil ----------
def _imagen(nombre="foto.png", contenido=None, tipo="image/png"):
    import base64

    from django.core.files.uploadedfile import SimpleUploadedFile

    if contenido is None:
        contenido = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            "+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    return SimpleUploadedFile(nombre, contenido, content_type=tipo)


def _empleado(cliente_rrhh, empresa):
    cliente_rrhh.post("/api/v1/empleados/", _payload_alta(empresa), format="json")
    return Empleado.objects.get(dni="30111222")


def test_foto_se_sube_y_se_sirve(cliente_rrhh, empresa, media_temporal):
    empleado = _empleado(cliente_rrhh, empresa)
    resp = cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/foto/", {"foto": _imagen()}, format="multipart"
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["tiene_foto"] is True
    assert resp.data["foto_url"] == f"/api/v1/empleados/{empleado.id}/foto/archivo/"

    empleado.refresh_from_db()
    # El nombre original se descarta (UUID); la ruta cuelga del id del empleado.
    assert "foto" not in empleado.foto.name.rsplit("/", 1)[-1].replace(".png", "")
    assert empleado.foto.name.startswith(f"fotos/{empleado.id}/")

    servida = cliente_rrhh.get(resp.data["foto_url"])
    assert servida.status_code == 200
    assert b"".join(servida.streaming_content).startswith(b"\x89PNG\r\n\x1a\n")
    # Se muestra inline (no adjunto): es una imagen de la ficha, no una descarga.
    assert "attachment" not in servida.get("Content-Disposition", "")
    evento = RegistroAuditoria.objects.get(
        accion=Accion.FOTO_CONSULTADA,
        objeto_id=empleado.id,
    )
    assert evento.entidad == "Empleado"
    assert evento.empleado_id == empleado.id
    assert evento.usuario_nombre == "rrhh"


def test_reemplazar_foto_borra_la_vieja(
    cliente_rrhh, empresa, media_temporal, django_capture_on_commit_callbacks
):
    empleado = _empleado(cliente_rrhh, empresa)
    cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/foto/",
        {"foto": _imagen("vieja.png")},
        format="multipart",
    )
    empleado.refresh_from_db()
    ruta_vieja = media_temporal / empleado.foto.name
    assert ruta_vieja.exists()

    with django_capture_on_commit_callbacks(execute=True):
        cliente_rrhh.post(
            f"/api/v1/empleados/{empleado.id}/foto/",
            {"foto": _imagen("nueva.png")},
            format="multipart",
        )
    empleado.refresh_from_db()
    assert not ruta_vieja.exists(), "la foto vieja quedó huérfana en MEDIA_ROOT"
    assert (media_temporal / empleado.foto.name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_eliminar_foto_se_lleva_el_archivo(
    cliente_rrhh, empresa, media_temporal, django_capture_on_commit_callbacks
):
    empleado = _empleado(cliente_rrhh, empresa)
    cliente_rrhh.post(
        f"/api/v1/empleados/{empleado.id}/foto/", {"foto": _imagen()}, format="multipart"
    )
    empleado.refresh_from_db()
    ruta = media_temporal / empleado.foto.name

    with django_capture_on_commit_callbacks(execute=True):
        resp = cliente_rrhh.delete(f"/api/v1/empleados/{empleado.id}/foto/")
    assert resp.status_code == 204
    empleado.refresh_from_db()
    assert not empleado.foto
    assert not ruta.exists()
    # Sin foto, la descarga da 404.
    assert cliente_rrhh.get(f"/api/v1/empleados/{empleado.id}/foto/archivo/").status_code == 404


def test_la_foto_solo_acepta_imagenes(cliente_rrhh, empresa, media_temporal, settings):
    empleado = _empleado(cliente_rrhh, empresa)
    url = f"/api/v1/empleados/{empleado.id}/foto/"

    # Un PDF sirve como respaldo de documento, pero no como foto (se muestra, no se descarga).
    resp = cliente_rrhh.post(
        url, {"foto": _imagen("doc.pdf", b"%PDF", "application/pdf")}, format="multipart"
    )
    assert resp.status_code == 400
    assert "pdf" in str(resp.data)

    settings.FOTO_MAX_BYTES = 1024
    resp = cliente_rrhh.post(
        url, {"foto": _imagen("grande.png", b"x" * 2048)}, format="multipart"
    )
    assert resp.status_code == 400
    assert "MB" in str(resp.data)


def test_empleado_no_puede_subir_foto(cliente_rrhh, empresa, crear_usuario, media_temporal):
    from rest_framework.test import APIClient

    from common import roles

    empleado = _empleado(cliente_rrhh, empresa)
    cliente = APIClient()
    cliente.force_authenticate(crear_usuario(username="peon", rol=roles.EMPLEADO))
    resp = cliente.post(
        f"/api/v1/empleados/{empleado.id}/foto/", {"foto": _imagen()}, format="multipart"
    )
    assert resp.status_code == 403


def test_la_foto_ajena_no_se_descarga(cliente_rrhh, empresa, crear_usuario, media_temporal):
    """El serve está scopeado igual que los documentos (A2): un empleado no baja la foto de
    otro, pero sí la suya."""
    from rest_framework.test import APIClient

    from common import roles

    ajeno = _empleado(cliente_rrhh, empresa)
    cliente_rrhh.post(
        f"/api/v1/empleados/{ajeno.id}/foto/", {"foto": _imagen()}, format="multipart"
    )

    propio = Empleado.objects.create(legajo="0500", dni="33444555", nombre="Otro", apellido="Tipo")
    usuario = crear_usuario(username="curioso2", rol=roles.EMPLEADO)
    propio.usuario = usuario
    propio.save()
    cliente = APIClient()
    cliente.force_authenticate(usuario)

    assert cliente.get(f"/api/v1/empleados/{ajeno.id}/foto/archivo/").status_code == 404
    # La suya (sin foto) da 404 por "no tiene", no por scope: llega al empleado.
    assert cliente.get(f"/api/v1/empleados/{propio.id}/foto/archivo/").status_code == 404


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
