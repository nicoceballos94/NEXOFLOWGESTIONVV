"""Fase 2: que cada service asiente su hecho, con el actor correcto y en el objeto correcto.

Los tests van por los **services reales** (no por `registrar_evento` directo): lo que puede
romperse acá no es el motor —eso lo cubre `test_auditoria.py`— sino que alguien agregue o
refactorice una operación de negocio y se olvide de asentarla. Es la falla silenciosa que
esta tanda existe para evitar: la bitácora no se queja, simplemente queda incompleta.
"""
from datetime import date

import pytest

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.empleados import services as emp_services
from apps.empleados.models import Empleado, EstadoRelacion, RelacionLaboral, TipoDocumento
from apps.novedades import services as nov_services
from apps.novedades.models import EstadoNovedad, TipoNovedad
from apps.organizacion.models import Empresa

pytestmark = pytest.mark.django_db


@pytest.fixture
def actor(crear_usuario):
    return crear_usuario(username="rrhh")


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="VIAL VICTORIA")


@pytest.fixture
def empleado(actor, empresa):
    return emp_services.crear_empleado(
        actor=actor,
        datos_empleado={"dni": "30111222", "nombre": "Juan", "apellido": "Pérez"},
        datos_relacion={"empresa": empresa, "fecha_ingreso": date(2024, 1, 10)},
    )


@pytest.fixture
def tipo_licencia():
    return TipoNovedad.objects.create(
        codigo="LICENCIA_MEDICA",
        nombre="Licencia médica",
        justifica_ausencia=True,
        ocupa_periodo=True,
        admite_prorroga=True,
    )


def _acciones(**filtros):
    return list(
        RegistroAuditoria.objects.filter(**filtros).order_by("id").values_list("accion", flat=True)
    )


# --- Empleados -------------------------------------------------------------------------


def test_el_alta_asienta_dos_hechos_la_persona_y_su_relacion(actor, empresa):
    emp_services.crear_empleado(
        actor=actor,
        datos_empleado={"dni": "30999888", "nombre": "Ana", "apellido": "Gómez"},
        datos_relacion={"empresa": empresa, "fecha_ingreso": date(2024, 3, 1)},
    )

    # Dos hechos distintos: la baja de mañana toca la relación, no la persona.
    assert _acciones() == [Accion.EMPLEADO_CREADO, Accion.RELACION_CREADA]
    assert RegistroAuditoria.objects.filter(usuario=actor).count() == 2


def test_editar_asienta_solo_lo_que_cambio(actor, empleado):
    RegistroAuditoria.objects.all().delete()

    emp_services.actualizar_empleado(
        actor=actor, empleado=empleado, datos_empleado={"telefono": "2664112233"}
    )

    registro = RegistroAuditoria.objects.get()
    assert registro.accion == Accion.EMPLEADO_ACTUALIZADO
    assert registro.valores_despues == {"telefono": "2664112233"}


def test_guardar_la_ficha_sin_tocarla_no_ensucia_la_bitacora(actor, empleado):
    RegistroAuditoria.objects.all().delete()

    emp_services.actualizar_empleado(
        actor=actor, empleado=empleado, datos_empleado={"nombre": "Juan"}
    )

    assert RegistroAuditoria.objects.count() == 0


def test_la_baja_deja_quien_cuando_y_por_que(actor, empleado, crear_usuario):
    quien_da_la_baja = crear_usuario(username="jefa_rrhh")
    relacion = empleado.relacion_activa
    RegistroAuditoria.objects.all().delete()

    emp_services.finalizar_relacion(
        actor=quien_da_la_baja,
        relacion=relacion,
        fecha_egreso=date(2026, 7, 1),
        motivo_egreso="RENUNCIA",
    )

    registro = RegistroAuditoria.objects.get()
    assert registro.accion == Accion.RELACION_FINALIZADA
    assert registro.usuario_nombre == "jefa_rrhh"
    assert registro.valores_antes["estado"] == EstadoRelacion.ACTIVA
    assert registro.valores_despues["estado"] == EstadoRelacion.FINALIZADA
    assert registro.valores_despues["motivo_egreso"] == "RENUNCIA"


def test_el_documento_borrado_deja_su_unica_constancia(actor, empleado):
    tipo = TipoDocumento.objects.create(nombre="APTO MÉDICO")
    documento = emp_services.crear_documento(
        actor=actor, empleado=empleado, tipo_documento=tipo, numero="A-1"
    )
    RegistroAuditoria.objects.all().delete()

    emp_services.eliminar_documento(actor=actor, documento=documento)

    # El DELETE es físico: si esto no quedara asentado, no quedaría rastro de que existió.
    registro = RegistroAuditoria.objects.get()
    assert registro.accion == Accion.DOCUMENTO_ELIMINADO
    assert registro.valores_antes["numero"] == "A-1"
    assert registro.valores_antes["tipo_documento"] == "APTO MÉDICO"
    assert registro.valores_despues == {}
    assert "APTO MÉDICO" in registro.objeto_repr


def test_la_foto_asienta_solo_la_foto_no_la_ficha_entera(actor, empleado):
    RegistroAuditoria.objects.all().delete()

    emp_services.guardar_foto_empleado(
        actor=actor, empleado=empleado, foto="fotos/1/nueva.jpg"
    )

    registro = RegistroAuditoria.objects.get()
    assert registro.accion == Accion.EMPLEADO_FOTO_CAMBIADA
    assert set(registro.valores_despues) == {"foto"}  # el DNI y el resto no son ruido acá


# --- Novedades -------------------------------------------------------------------------


def _crear_novedad(actor, empleado, tipo, desde=date(2026, 8, 1), hasta=date(2026, 8, 10)):
    return nov_services.crear_novedad(
        actor=actor,
        datos={
            "empleado": empleado,
            "tipo_novedad": tipo,
            "fecha_desde": desde,
            "fecha_hasta": hasta,
        },
    )


def test_cada_transicion_de_la_novedad_queda_con_su_nombre(actor, empleado, tipo_licencia):
    novedad = _crear_novedad(actor, empleado, tipo_licencia)
    nov_services.aprobar_novedad(actor=actor, novedad=novedad)

    assert _acciones(entidad="Novedad") == [Accion.NOVEDAD_CREADA, Accion.NOVEDAD_APROBADA]


def test_el_motivo_del_rechazo_queda_como_dato_no_pegado_en_observaciones(
    actor, empleado, tipo_licencia, crear_usuario
):
    novedad = _crear_novedad(actor, empleado, tipo_licencia)
    quien_rechaza = crear_usuario(username="jefa_rrhh")
    RegistroAuditoria.objects.all().delete()

    nov_services.rechazar_novedad(
        actor=quien_rechaza, novedad=novedad, motivo="Sin certificado médico"
    )

    registro = RegistroAuditoria.objects.get()
    assert registro.accion == Accion.NOVEDAD_RECHAZADA
    assert registro.usuario_nombre == "jefa_rrhh"
    # Este era el punto flojo del D2: el motivo vivía concatenado en un texto editable.
    assert registro.valores_despues["motivo_rechazo"] == "Sin certificado médico"
    assert registro.valores_despues["estado"] == EstadoNovedad.RECHAZADA


def test_anular_asienta_su_motivo(actor, empleado, tipo_licencia):
    novedad = _crear_novedad(actor, empleado, tipo_licencia)
    RegistroAuditoria.objects.all().delete()

    nov_services.anular_novedad(actor=actor, novedad=novedad, motivo="Cargada por error")

    registro = RegistroAuditoria.objects.get()
    assert registro.accion == Accion.NOVEDAD_ANULADA
    assert registro.valores_despues["motivo_anulacion"] == "Cargada por error"


def test_la_prorroga_se_asienta_en_la_madre_no_en_el_eslabon_nuevo(
    actor, empleado, tipo_licencia
):
    madre = _crear_novedad(actor, empleado, tipo_licencia)
    nov_services.aprobar_novedad(actor=actor, novedad=madre)
    RegistroAuditoria.objects.all().delete()

    prorroga = nov_services.prorrogar_novedad(
        actor=actor, novedad=madre, fecha_hasta_nueva=date(2026, 8, 20), motivo="Sigue de licencia"
    )

    registro = RegistroAuditoria.objects.get()
    assert registro.accion == Accion.NOVEDAD_PRORROGADA
    # Quien audita abre la licencia madre y espera ver ahí que la cadena creció.
    assert registro.objeto_id == madre.pk
    assert registro.valores_despues["prorroga_id"] == prorroga.pk
    assert registro.valores_despues["prorrogada_hasta"] == "2026-08-20"


def test_el_adjunto_se_asienta_en_la_novedad_y_solo_con_su_nombre(
    actor, empleado, tipo_licencia
):
    novedad = _crear_novedad(actor, empleado, tipo_licencia)
    RegistroAuditoria.objects.all().delete()

    adjunto = nov_services.adjuntar_a_novedad(
        actor=actor, novedad=novedad, archivo="adjuntos/1/certificado.pdf"
    )
    nov_services.quitar_adjunto(actor=actor, adjunto=adjunto)

    assert _acciones() == [Accion.ADJUNTO_AGREGADO, Accion.ADJUNTO_ELIMINADO]
    for registro in RegistroAuditoria.objects.all():
        assert registro.objeto_id == novedad.pk  # nadie navega la lista de adjuntos sola


# --- La bitácora viaja en la misma transacción que el negocio --------------------------


def test_si_la_operacion_se_cae_no_queda_un_evento_huerfano(actor, empresa):
    """Media alta que igual dejó "empleado creado" en la bitácora sería peor que nada."""
    from django.db.utils import IntegrityError

    with pytest.raises(IntegrityError):
        emp_services.crear_empleado(
            actor=actor,
            datos_empleado={"dni": "30777666", "nombre": "Rita", "apellido": "Suárez"},
            datos_relacion={"empresa": empresa},  # sin fecha_ingreso: revienta en la DB
        )

    assert not Empleado.objects.filter(dni="30777666").exists()
    assert RegistroAuditoria.objects.count() == 0


def test_un_proceso_sin_usuario_no_rompe_el_alta(empresa):
    """Los comandos de seed llaman a los services con `actor=None`."""
    emp_services.crear_empleado(
        actor=None,
        datos_empleado={"dni": "30555444", "nombre": "Seed", "apellido": "Automático"},
        datos_relacion={"empresa": empresa, "fecha_ingreso": date(2024, 1, 10)},
    )

    assert RelacionLaboral.objects.count() == 1
    assert RegistroAuditoria.objects.filter(usuario__isnull=True).count() == 2


# --- Onboarding / offboarding ----------------------------------------------------------


@pytest.fixture
def item_checklist(actor, empleado, empresa):
    from apps.onboarding import services as onb_services
    from apps.onboarding.models import TipoItem, TipoProceso

    plantilla = onb_services.crear_plantilla(
        actor=actor, empresa=empresa, tipo_proceso=TipoProceso.INGRESO
    )
    onb_services.agregar_item(
        actor=actor, plantilla=plantilla, etiqueta="Alta AFIP/ARCA", tipo_item=TipoItem.ACCION
    )
    proceso = onb_services.obtener_o_crear_proceso(
        actor=actor, relacion=empleado.relacion_activa, tipo_proceso=TipoProceso.INGRESO
    )
    return proceso.items.get()


def test_destildar_un_item_deja_el_rastro_que_el_propio_item_borra(actor, item_checklist):
    from apps.onboarding import services as onb_services

    onb_services.tildar_item(actor=actor, item=item_checklist, hecho=True)
    RegistroAuditoria.objects.all().delete()

    onb_services.tildar_item(actor=actor, item=item_checklist, hecho=False)

    # Al destildar, `completado_por` se borra del ítem: sin esto no quedaría ni rastro
    # de que estuvo hecho, ni de quién lo revirtió.
    registro = RegistroAuditoria.objects.get()
    assert registro.accion == Accion.CHECKLIST_ITEM_REVERTIDO
    assert registro.valores_antes == {"completado": True}
    assert registro.valores_despues == {"completado": False}
    assert "Alta AFIP/ARCA" in registro.objeto_repr


def test_volver_a_tildar_lo_ya_tildado_no_es_un_hecho_nuevo(actor, item_checklist):
    from apps.onboarding import services as onb_services

    onb_services.tildar_item(actor=actor, item=item_checklist, hecho=True)
    RegistroAuditoria.objects.all().delete()

    onb_services.tildar_item(actor=actor, item=item_checklist, hecho=True)

    assert RegistroAuditoria.objects.count() == 0


# --- Usuarios (por el admin: en MVP1 no hay ABM por API) -------------------------------


@pytest.fixture
def admin_logueado(client, django_user_model):
    django_user_model.objects.create_superuser(username="jefe", password="clave-segura-123")
    client.login(username="jefe", password="clave-segura-123")
    return client


def test_crear_un_usuario_desde_el_admin_queda_asentado(admin_logueado):
    resp = admin_logueado.post(
        "/admin/usuarios/usuario/add/",
        {
            "username": "nuevo_rrhh",
            "password1": "clave-segura-123",
            "password2": "clave-segura-123",
        },
    )

    assert resp.status_code == 302, "el alta no pasó la validación del form"
    registro = RegistroAuditoria.objects.get(entidad="Usuario")
    assert registro.accion == Accion.USUARIO_CREADO
    assert registro.usuario_nombre == "jefe"
    assert registro.valores_despues["username"] == "nuevo_rrhh"
    assert registro.valores_despues["password"] == "«oculto»"


def test_el_cambio_de_rol_queda_asentado(admin_logueado, crear_usuario):
    from django.contrib.auth.models import Group

    from common import roles

    usuario = crear_usuario(username="asciende")
    grupo_admin = Group.objects.create(name=roles.ADMIN)
    RegistroAuditoria.objects.all().delete()

    resp = admin_logueado.post(
        f"/admin/usuarios/usuario/{usuario.pk}/change/",
        {
            "username": "asciende",
            "first_name": "",
            "last_name": "",
            "email": "",
            "is_active": "on",
            "date_joined_0": "2026-01-01",
            "date_joined_1": "00:00:00",
            "groups": [str(grupo_admin.pk)],
        },
    )

    assert resp.status_code == 302, "la edición no pasó la validación del form"
    # Quién es Admin y desde cuándo: los roles son Grupos y no dejan huella en la fila.
    registro = RegistroAuditoria.objects.get(entidad="Usuario")
    assert registro.accion == Accion.USUARIO_ACTUALIZADO
    assert registro.valores_antes["roles"] == []
    assert registro.valores_despues["roles"] == [roles.ADMIN]


def test_desactivar_un_usuario_tiene_nombre_propio(admin_logueado, crear_usuario):
    usuario = crear_usuario(username="se_va")
    RegistroAuditoria.objects.all().delete()

    resp = admin_logueado.post(
        f"/admin/usuarios/usuario/{usuario.pk}/change/",
        {
            "username": "se_va",
            "first_name": "",
            "last_name": "",
            "email": "",
            "date_joined_0": "2026-01-01",
            "date_joined_1": "00:00:00",
            # sin is_active: el checkbox desmarcado no se envía
        },
    )

    assert resp.status_code == 302
    registro = RegistroAuditoria.objects.get(entidad="Usuario")
    assert registro.accion == Accion.USUARIO_DESACTIVADO
    assert registro.valores_despues["is_active"] is False
