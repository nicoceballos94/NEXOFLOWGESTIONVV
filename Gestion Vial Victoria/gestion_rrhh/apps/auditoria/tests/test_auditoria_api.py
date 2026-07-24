"""Fase 3: la API de consulta. Quién puede leerla, cómo se filtra y qué NO se puede hacer.

El test de permisos es el que más importa: esta tabla concentra el PII más sensible del
sistema (DNI y CUIL en los diffs de empleado, motivos médicos en los de novedad) en texto
plano, sin los serializers por rol que lo protegen en sus endpoints de origen.
"""
from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.auditoria.services import registrar_evento, tomar_foto
from apps.empleados import services as emp_services
from apps.empleados.models import Empleado
from apps.organizacion.models import Empresa
from common import roles

pytestmark = pytest.mark.django_db

URL = "/api/v1/auditoria/registros/"


def _cliente(crear_usuario, rol, username):
    cliente = APIClient()
    cliente.force_authenticate(crear_usuario(username=username, rol=rol))
    return cliente


@pytest.fixture
def cliente_admin(crear_usuario):
    return _cliente(crear_usuario, roles.ADMIN, "jefe")


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="VIAL VICTORIA")


@pytest.fixture
def actor(crear_usuario):
    return crear_usuario(username="rrhh", rol=roles.RRHH)


@pytest.fixture
def empleado(actor, empresa):
    return emp_services.crear_empleado(
        actor=actor,
        datos_empleado={"dni": "30111222", "nombre": "Juan", "apellido": "Pérez"},
        datos_relacion={"empresa": empresa, "fecha_ingreso": date(2024, 1, 10)},
    )


# --- Permisos ---------------------------------------------------------------------------


def test_admin_lee_la_bitacora(cliente_admin, empleado):
    resp = cliente_admin.get(URL)

    assert resp.status_code == 200
    assert resp.data["count"] == 2  # alta de la persona + de su relación


@pytest.mark.parametrize(
    "rol", [roles.RRHH, roles.SUPERVISOR, roles.EMPLEADO, roles.SERVICIO]
)
def test_ningun_otro_rol_entra(crear_usuario, empleado, rol):
    """RRHH incluido, y es el punto: es el rol que más aparece auditado."""
    cliente = _cliente(crear_usuario, rol, f"usuario_{rol.lower()}")

    assert cliente.get(URL).status_code == 403


def test_sin_autenticar_no_entra(empleado):
    assert APIClient().get(URL).status_code == 401


# --- Filtros ----------------------------------------------------------------------------


def test_el_historial_de_una_ficha_sale_de_un_solo_filtro(cliente_admin, actor, empleado):
    otro = emp_services.crear_empleado(
        actor=actor,
        datos_empleado={"dni": "30999888", "nombre": "Ana", "apellido": "Gómez"},
        datos_relacion={"empresa": Empresa.objects.first(), "fecha_ingreso": date(2024, 5, 1)},
    )

    resp = cliente_admin.get(URL, {"empleado": empleado.pk})

    assert resp.status_code == 200
    assert resp.data["count"] == 2
    assert all(r["empleado"] == empleado.pk for r in resp.data["results"])
    assert not any(r["empleado"] == otro.pk for r in resp.data["results"])


def test_se_puede_pedir_la_historia_de_un_objeto_puntual(cliente_admin, empleado):
    resp = cliente_admin.get(URL, {"entidad": "RelacionLaboral"})

    assert resp.data["count"] == 1
    assert resp.data["results"][0]["accion"] == Accion.RELACION_CREADA


def test_se_filtra_por_quien_lo_hizo(cliente_admin, actor, empleado, crear_usuario):
    otra = crear_usuario(username="otra_rrhh", rol=roles.RRHH)
    emp_services.actualizar_empleado(
        actor=otra, empleado=empleado, datos_empleado={"telefono": "2664112233"}
    )

    resp = cliente_admin.get(URL, {"usuario": otra.pk})

    assert resp.data["count"] == 1
    assert resp.data["results"][0]["usuario_nombre"] == "otra_rrhh"


def test_el_rango_de_fechas_incluye_el_dia_entero(cliente_admin, empleado):
    """`momento` es un datetime: comparado crudo contra una fecha, "hoy" solo tomaría la
    medianoche exacta y el filtro devolvería vacío justo el día que interesa."""
    hoy = timezone.localdate()

    resp = cliente_admin.get(URL, {"desde": hoy.isoformat(), "hasta": hoy.isoformat()})

    assert resp.data["count"] == 2


def test_un_rango_que_no_incluye_hoy_no_devuelve_nada(cliente_admin, empleado):
    ayer = (timezone.localdate() - timedelta(days=1)).isoformat()

    resp = cliente_admin.get(URL, {"desde": ayer, "hasta": ayer})

    assert resp.data["count"] == 0


def test_lo_mas_nuevo_primero(cliente_admin, actor, empleado):
    emp_services.actualizar_empleado(
        actor=actor, empleado=empleado, datos_empleado={"telefono": "2664112233"}
    )

    acciones = [r["accion"] for r in cliente_admin.get(URL).data["results"]]

    assert acciones[0] == Accion.EMPLEADO_ACTUALIZADO


# --- Forma de la respuesta ---------------------------------------------------------------


def test_los_cambios_vienen_listos_para_pintar(cliente_admin, actor, empleado):
    RegistroAuditoria.objects.all().delete()
    emp_services.actualizar_empleado(
        actor=actor, empleado=empleado, datos_empleado={"telefono": "2664112233"}
    )

    registro = cliente_admin.get(URL).data["results"][0]

    # Una lista de {campo, antes, despues}, no dos diccionarios que el front tenga que cruzar.
    assert registro["cambios"] == [
        {"campo": "telefono", "antes": "", "despues": "2664112233"}
    ]
    assert registro["accion_display"] == "Empleado actualizado"
    assert registro["empleado_nombre"] == "Juan Pérez"


def test_una_baja_se_lee_entera_desde_la_api(cliente_admin, actor, empleado):
    RegistroAuditoria.objects.all().delete()
    emp_services.finalizar_relacion(
        actor=actor,
        relacion=empleado.relacion_activa,
        fecha_egreso=date(2026, 7, 1),
        motivo_egreso="RENUNCIA",
    )

    registro = cliente_admin.get(URL).data["results"][0]
    cambios = {c["campo"]: (c["antes"], c["despues"]) for c in registro["cambios"]}

    assert registro["accion_display"] == "Relación laboral finalizada (baja)"
    assert registro["usuario_nombre"] == "rrhh"
    assert cambios["estado"] == ("ACTIVA", "FINALIZADA")
    assert cambios["motivo_egreso"] == ("", "RENUNCIA")


# --- La bitácora no se escribe por API ---------------------------------------------------


def test_no_se_puede_escribir_la_bitacora(cliente_admin, empleado):
    registro = RegistroAuditoria.objects.first()

    assert cliente_admin.post(URL, {}, format="json").status_code == 405
    assert cliente_admin.patch(f"{URL}{registro.pk}/", {}, format="json").status_code == 405
    assert cliente_admin.delete(f"{URL}{registro.pk}/").status_code == 405
    assert RegistroAuditoria.objects.count() == 2


# --- Performance -------------------------------------------------------------------------


def test_la_lista_no_dispara_un_query_por_renglon(
    cliente_admin, actor, empresa, django_assert_max_num_queries
):
    """Sin `select_related`, serializar 25 renglones cuesta 50 queries extra (autor y
    persona de cada uno) y la pantalla de bitácora se vuelve inusable."""
    for i in range(10):
        empleado = Empleado.objects.create(
            legajo=f"9{i:03d}", dni=f"4000000{i}", nombre=f"N{i}", apellido=f"A{i}"
        )
        registrar_evento(
            actor=actor,
            accion=Accion.EMPLEADO_ACTUALIZADO,
            objeto=empleado,
            antes=tomar_foto(empleado),
            despues={"telefono": "266"},
        )

    # auth + count + página; el margen cubre lo que agregue DRF, no un N+1 (que serían 20+).
    with django_assert_max_num_queries(8):
        resp = cliente_admin.get(URL)

    assert resp.data["count"] == 10
