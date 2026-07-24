"""Contrato de `empleado_id`: el historial de una ficha sale de UNA consulta.

La columna está denormalizada, y toda denormalización se pudre igual: alguien agrega una
entidad auditable, se olvida de declarar dónde está su persona, y el evento se guarda con
`empleado=None`. Nada falla — la ficha simplemente deja de mostrar una parte de la historia,
y nadie se entera hasta que hace falta en una discusión.

Estos tests son la red contra eso. El de abajo (`test_toda_la_vida_laboral_...`) es el que
importa: recorre una vida laboral completa por los services reales y exige que **ni un solo
evento** quede sin persona.
"""
import pytest
from django.apps import apps as django_apps

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.auditoria.services import _empleado_de
from apps.empleados import services as emp_services
from apps.empleados.models import DocumentoEmpleado, Empleado, RelacionLaboral, TipoDocumento
from apps.novedades import services as nov_services
from apps.novedades.models import Novedad, TipoNovedad
from apps.onboarding import services as onb_services
from apps.onboarding.models import ItemProceso, TipoItem, TipoProceso
from apps.organizacion.models import Empresa, Puesto, Sector
from apps.usuarios.models import Usuario

pytestmark = pytest.mark.django_db

# Toda entidad que `registrar_evento` pueda recibir como `objeto`. Si agregás una acción
# nueva al enum sobre un modelo que no está acá, sumalo: es la lista que sostiene el contrato.
ENTIDADES_AUDITADAS = [
    Empleado,
    RelacionLaboral,
    DocumentoEmpleado,
    Novedad,
    ItemProceso,
    Usuario,
]


def test_toda_entidad_auditada_declara_donde_esta_su_persona():
    """`no tiene la propiedad` tiene que significar siempre "se la olvidaron"."""
    sin_declarar = [
        modelo.__name__
        for modelo in ENTIDADES_AUDITADAS
        if not isinstance(getattr(modelo, "empleado_auditado", None), property)
    ]
    assert sin_declarar == [], (
        f"Estos modelos se auditan pero no declaran `empleado_auditado`: {sin_declarar}. "
        "Sus eventos van a guardarse sin persona y no van a aparecer en la ficha."
    )


def test_las_entidades_auditadas_existen_todavia():
    """Si alguien renombra o borra un modelo, esta lista queda mintiendo en silencio."""
    for modelo in ENTIDADES_AUDITADAS:
        assert django_apps.get_model(modelo._meta.label) is modelo


def test_un_usuario_no_es_de_nadie(crear_usuario):
    """Explícito: darle un rol a alguien no es un hecho de su legajo de RRHH."""
    assert _empleado_de(crear_usuario(username="alguien")) is None


def test_un_usuario_enlazado_a_un_empleado_tampoco(crear_usuario):
    usuario = crear_usuario(username="juan")
    Empleado.objects.create(
        legajo="0001", dni="30111222", nombre="Juan", apellido="Pérez", usuario=usuario
    )

    # Aunque el enlace exista, son dos historias que se leen por motivos distintos.
    assert _empleado_de(usuario) is None


# --- El test que importa ---------------------------------------------------------------


def test_toda_la_vida_laboral_de_una_persona_cae_bajo_su_ficha(crear_usuario):
    """La historia personal queda bajo la ficha; la parametría sigue siendo global."""
    from datetime import date

    actor = crear_usuario(username="rrhh")
    empresa = Empresa.objects.create(nombre="VIAL VICTORIA")
    sector = Sector.objects.create(nombre="Operaciones")
    puesto = Puesto.objects.create(nombre="Chofer", sector=sector)
    tipo_doc = TipoDocumento.objects.create(nombre="APTO MÉDICO")
    tipo_nov = TipoNovedad.objects.create(
        codigo="LICENCIA_MEDICA",
        nombre="Licencia médica",
        ocupa_periodo=True,
        admite_prorroga=True,
    )

    # 1. Alta (empleado + relación)
    empleado = emp_services.crear_empleado(
        actor=actor,
        datos_empleado={"dni": "30111222", "nombre": "Juan", "apellido": "Pérez"},
        datos_relacion={
            "empresa": empresa,
            "sector": sector,
            "puesto": puesto,
            "fecha_ingreso": date(2024, 1, 10),
        },
    )
    # 2. Edición de la ficha
    emp_services.actualizar_empleado(
        actor=actor, empleado=empleado, datos_empleado={"telefono": "2664112233"}
    )
    # 3. Documento del legajo
    documento = emp_services.crear_documento(
        actor=actor, empleado=empleado, tipo_documento=tipo_doc, numero="A-1"
    )
    emp_services.eliminar_documento(actor=actor, documento=documento)
    # 4. Checklist de ingreso
    plantilla = onb_services.crear_plantilla(
        actor=actor, empresa=empresa, tipo_proceso=TipoProceso.INGRESO
    )
    onb_services.agregar_item(
        actor=actor, plantilla=plantilla, etiqueta="Alta AFIP/ARCA", tipo_item=TipoItem.ACCION
    )
    onb_services.publicar_plantilla(actor=actor, plantilla=plantilla)
    proceso = onb_services.obtener_o_crear_proceso(
        actor=actor, relacion=empleado.relacion_activa, tipo_proceso=TipoProceso.INGRESO
    )
    onb_services.tildar_item(actor=actor, item=proceso.items.get(), hecho=True)
    # 5. Novedad, con prórroga y adjunto
    novedad = nov_services.crear_novedad(
        actor=actor,
        datos={
            "empleado": empleado,
            "tipo_novedad": tipo_nov,
            "fecha_desde": date(2026, 8, 1),
            "fecha_hasta": date(2026, 8, 10),
        },
    )
    nov_services.aprobar_novedad(actor=actor, novedad=novedad)
    nov_services.prorrogar_novedad(
        actor=actor, novedad=novedad, fecha_hasta_nueva=date(2026, 8, 20)
    )
    adjunto = nov_services.adjuntar_a_novedad(
        actor=actor, novedad=novedad, archivo="novedades/1/cert.pdf"
    )
    nov_services.quitar_adjunto(actor=actor, adjunto=adjunto)
    # 6. Baja
    emp_services.finalizar_relacion(
        actor=actor,
        relacion=empleado.relacion_activa,
        fecha_egreso=date(2026, 8, 31),
        motivo_egreso="RENUNCIA",
    )

    # Crear/publicar una plantilla y definir sus renglones son cambios globales de
    # parametría, anteriores a cualquier proceso personal. No deben atribuirse
    # artificialmente al empleado que luego use esa plantilla.
    globales = RegistroAuditoria.objects.filter(empleado__isnull=True)
    assert set(globales.values_list("entidad", "accion")) == {
        ("PlantillaChecklist", Accion.PLANTILLA_CREADA),
        ("PlantillaChecklist", Accion.PLANTILLA_PUBLICADA),
        ("ItemPlantilla", Accion.PLANTILLA_ITEM_CREADO),
    }

    # Y este es el punto de la columna: la historia completa, en una sola consulta.
    historial = RegistroAuditoria.objects.filter(empleado=empleado)
    assert historial.count() + globales.count() == RegistroAuditoria.objects.count()
    # Seis entidades distintas, todas bajo la misma ficha.
    assert set(historial.values_list("entidad", flat=True)) == {
        "Empleado",
        "RelacionLaboral",
        "DocumentoEmpleado",
        "ProcesoEmpleado",
        "ItemProceso",
        "Novedad",
    }
