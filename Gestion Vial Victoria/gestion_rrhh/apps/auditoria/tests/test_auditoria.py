"""Tests del motor de bitácora: qué se guarda, qué NO se guarda y qué no se guarda dos veces.

Fase 1 = el motor. Que cada service llame a `registrar_evento` en el momento correcto se
prueba en los tests de cada app, cuando se cablee (fase 2).
"""
import pytest

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.auditoria.services import registrar_evento, tomar_foto
from apps.empleados.models import Empleado, EstadoRelacion, RelacionLaboral
from apps.organizacion.models import Empresa

pytestmark = pytest.mark.django_db


@pytest.fixture
def empresa():
    return Empresa.objects.create(nombre="VIAL VICTORIA")


@pytest.fixture
def empleado():
    return Empleado.objects.create(
        legajo="0001", dni="30111222", nombre="Juan", apellido="Pérez"
    )


def test_alta_guarda_el_estado_completo_y_nada_del_lado_de_antes(crear_usuario, empleado):
    actor = crear_usuario(username="rrhh1")

    registro = registrar_evento(
        actor=actor, accion=Accion.EMPLEADO_CREADO, objeto=empleado
    )

    assert registro.valores_antes == {}
    assert registro.valores_despues["dni"] == "30111222"
    assert registro.valores_despues["apellido"] == "Pérez"
    assert registro.entidad == "Empleado"
    assert registro.objeto_id == empleado.pk
    assert registro.usuario == actor
    assert registro.usuario_nombre == "rrhh1"


def test_edicion_guarda_solo_los_campos_que_cambiaron(crear_usuario, empleado):
    foto = tomar_foto(empleado)
    empleado.telefono = "2664112233"
    empleado.save()

    registro = registrar_evento(
        actor=crear_usuario(username="rrhh2"),
        accion=Accion.EMPLEADO_ACTUALIZADO,
        objeto=empleado,
        antes=foto,
    )

    # El diff es el punto: guardar la fila entera dos veces obligaría a leerla comparando.
    assert registro.valores_antes == {"telefono": ""}
    assert registro.valores_despues == {"telefono": "2664112233"}


def test_guardar_sin_cambiar_nada_no_deja_renglon(crear_usuario, empleado):
    foto = tomar_foto(empleado)
    empleado.save()  # abrir la ficha y guardar sin tocar nada

    registro = registrar_evento(
        actor=crear_usuario(username="rrhh3"),
        accion=Accion.EMPLEADO_ACTUALIZADO,
        objeto=empleado,
        antes=foto,
        solo_si_cambia=True,
    )

    assert registro is None
    assert RegistroAuditoria.objects.count() == 0


def test_las_fk_se_congelan_como_texto_legible(crear_usuario, empleado, empresa):
    relacion = RelacionLaboral.objects.create(
        empleado=empleado, empresa=empresa, fecha_ingreso="2024-01-10"
    )

    registro = registrar_evento(
        actor=crear_usuario(username="rrhh4"),
        accion=Accion.RELACION_CREADA,
        objeto=relacion,
    )

    # "VIAL VICTORIA", no 1: dentro de dos años el id puede apuntar a otra empresa.
    assert registro.valores_despues["empresa"] == str(empresa)
    assert registro.valores_despues["empleado"] == str(empleado)


def test_la_baja_deja_constancia_de_a_quien_se_referia(crear_usuario, empleado, empresa):
    relacion = RelacionLaboral.objects.create(
        empleado=empleado, empresa=empresa, fecha_ingreso="2024-01-10"
    )
    foto = tomar_foto(relacion)
    relacion.estado = EstadoRelacion.FINALIZADA
    relacion.fecha_egreso = "2026-07-01"
    relacion.motivo_egreso = "RENUNCIA"
    relacion.save()

    registro = registrar_evento(
        actor=crear_usuario(username="rrhh5"),
        accion=Accion.RELACION_FINALIZADA,
        objeto=relacion,
        antes=foto,
    )

    assert registro.valores_antes["estado"] == "ACTIVA"
    assert registro.valores_despues["estado"] == "FINALIZADA"
    assert registro.valores_despues["motivo_egreso"] == "RENUNCIA"
    assert str(empleado) in registro.objeto_repr


def test_borrado_se_asienta_pasando_despues_vacio(crear_usuario, empleado):
    foto = tomar_foto(empleado)

    # Se registra ANTES del delete: después, Django deja el objeto sin pk.
    registro = registrar_evento(
        actor=crear_usuario(username="rrhh6"),
        accion=Accion.EMPLEADO_ACTUALIZADO,
        objeto=empleado,
        antes=foto,
        despues={},
    )

    assert registro.valores_despues == {}
    assert registro.valores_antes["dni"] == "30111222"
    assert registro.objeto_id is not None


def test_los_metadatos_de_la_fila_no_ensucian_el_diff(crear_usuario, empleado):
    registro = registrar_evento(
        actor=crear_usuario(username="rrhh7"), accion=Accion.EMPLEADO_CREADO, objeto=empleado
    )

    for ruido in ("id", "creado_en", "actualizado_en", "creado_por"):
        assert ruido not in registro.valores_despues


def test_nunca_se_asienta_una_contrasena(crear_usuario):
    usuario = crear_usuario(username="alguien")

    registro = registrar_evento(
        actor=usuario, accion=Accion.USUARIO_CREADO, objeto=usuario
    )

    assert registro.valores_despues["password"] == "«oculto»"
    assert "clave-segura-123" not in str(registro.valores_despues)


def test_un_proceso_automatico_se_asienta_sin_autor(empleado):
    """`actor=None` es un proceso del sistema, no un error: la constancia igual se guarda."""
    registro = registrar_evento(actor=None, accion=Accion.EMPLEADO_CREADO, objeto=empleado)

    assert registro.usuario is None
    assert registro.usuario_nombre == ""


def test_el_autor_sobrevive_al_borrado_del_usuario(crear_usuario, empleado):
    actor = crear_usuario(username="se-va-de-la-empresa")
    registro = registrar_evento(
        actor=actor, accion=Accion.EMPLEADO_CREADO, objeto=empleado
    )

    actor.delete()
    registro.refresh_from_db()

    # La FK es SET_NULL, pero el nombre congelado mantiene la bitácora con autor.
    assert registro.usuario is None
    assert registro.usuario_nombre == "se-va-de-la-empresa"


def test_de_un_archivo_se_guarda_el_nombre_nunca_el_contenido(crear_usuario, empleado):
    empleado.foto = "fotos/42/abc-def.jpg"
    empleado.save()

    registro = registrar_evento(
        actor=crear_usuario(username="rrhh8"), accion=Accion.EMPLEADO_CREADO, objeto=empleado
    )

    assert registro.valores_despues["foto"] == "fotos/42/abc-def.jpg"


def test_la_foto_puede_acotarse_a_los_campos_que_importan(empleado):
    foto = tomar_foto(empleado, campos=("nombre", "apellido"))

    assert set(foto) == {"nombre", "apellido"}


# --- La bitácora en el admin: la superficie de consulta de la fase 1 ---


@pytest.fixture
def admin_logueado(client, django_user_model):
    django_user_model.objects.create_superuser(username="jefe", password="clave-segura-123")
    client.login(username="jefe", password="clave-segura-123")
    return client


def test_el_admin_lista_la_bitacora_con_el_diff_renderizado(
    admin_logueado, crear_usuario, empleado
):
    foto = tomar_foto(empleado)
    empleado.telefono = "2664112233"
    empleado.save()
    registrar_evento(
        actor=crear_usuario(username="rrhh9"),
        accion=Accion.EMPLEADO_ACTUALIZADO,
        objeto=empleado,
        antes=foto,
    )

    resp = admin_logueado.get("/admin/auditoria/registroauditoria/")

    assert resp.status_code == 200
    cuerpo = resp.content.decode()
    # El diff se muestra como HTML, no como marcado escapado a la vista del usuario.
    assert "<b>telefono</b>" in cuerpo
    assert "2664112233" in cuerpo
    assert "rrhh9" in cuerpo


def test_el_admin_no_deja_tocar_la_bitacora(admin_logueado, empleado):
    registro = registrar_evento(actor=None, accion=Accion.EMPLEADO_CREADO, objeto=empleado)

    # Una bitácora que el auditado puede retocar no es una bitácora, ni siendo superusuario.
    assert admin_logueado.get("/admin/auditoria/registroauditoria/add/").status_code == 403
    borrar = f"/admin/auditoria/registroauditoria/{registro.pk}/delete/"
    assert admin_logueado.get(borrar).status_code == 403
    assert RegistroAuditoria.objects.count() == 1
