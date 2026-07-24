"""Tests de onboarding/offboarding (CU-29 / CU-30).

Cubren lo que sostiene el diseño:
- Los CheckConstraint de la DB (verificados contra Postgres, no SQLite).
- El ítem DOCUMENTAL se completa solo al cargar el documento; no se tilda a mano.
- La creación perezosa del proceso es idempotente.
- La matriz de permisos: el ABM y el tildado son de RRHH/Admin.
"""
import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.empleados.models import (
    DocumentoEmpleado,
    Empleado,
    EstadoRelacion,
    RelacionLaboral,
    TipoDocumento,
)
from apps.onboarding import selectors, services
from apps.onboarding.models import (
    ItemPlantilla,
    PlantillaChecklist,
    TipoItem,
    TipoProceso,
)
from apps.organizacion.models import Empresa, Puesto, Sector

pytestmark = pytest.mark.django_db


@pytest.fixture
def empresa():
    empresa = Empresa.objects.create(nombre="VIAL VICTORIA")
    empresa._sector_prueba = Sector.objects.create(nombre="Operaciones")
    empresa._puesto_prueba = Puesto.objects.create(
        nombre="Chofer", sector=empresa._sector_prueba
    )
    return empresa


@pytest.fixture
def tipo_doc():
    return TipoDocumento.objects.create(nombre="Contrato")


@pytest.fixture
def empleado_activo(empresa):
    e = Empleado.objects.create(legajo="0001", dni="30111222", nombre="Juan", apellido="Pérez")
    RelacionLaboral.objects.create(
        empleado=e,
        empresa=empresa,
        sector=empresa._sector_prueba,
        puesto=empresa._puesto_prueba,
        fecha_ingreso=timezone.localdate(),
        estado=EstadoRelacion.ACTIVA,
    )
    return e


@pytest.fixture
def plantilla_con_items(empresa, tipo_doc):
    """Plantilla de ingreso con un ítem ACCION y uno DOCUMENTAL (enlazado a 'Contrato')."""
    pl = services.crear_plantilla(actor=None, empresa=empresa, tipo_proceso=TipoProceso.INGRESO)
    services.agregar_item(actor=None, plantilla=pl, etiqueta="Uniforme", tipo_item=TipoItem.ACCION)
    services.agregar_item(
        actor=None,
        plantilla=pl,
        etiqueta="Firma contrato",
        tipo_item=TipoItem.DOCUMENTAL,
        tipo_documento=tipo_doc,
    )
    services.publicar_plantilla(actor=None, plantilla=pl)
    return pl


# --- Constraints en Postgres -----------------------------------------------------------

def test_item_documental_sin_tipo_lo_rechaza_la_db(empresa):
    pl = PlantillaChecklist.objects.create(empresa=empresa, tipo_proceso=TipoProceso.INGRESO)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ItemPlantilla.objects.create(
                plantilla=pl, etiqueta="Mal", tipo_item=TipoItem.DOCUMENTAL, tipo_documento=None
            )


def test_item_accion_con_tipo_lo_rechaza_la_db(empresa, tipo_doc):
    pl = PlantillaChecklist.objects.create(empresa=empresa, tipo_proceso=TipoProceso.INGRESO)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ItemPlantilla.objects.create(
                plantilla=pl, etiqueta="Mal", tipo_item=TipoItem.ACCION, tipo_documento=tipo_doc
            )


def test_publicar_version_nueva_archiva_la_anterior(empresa):
    primera = services.crear_plantilla(
        actor=None, empresa=empresa, tipo_proceso=TipoProceso.INGRESO
    )
    services.publicar_plantilla(actor=None, plantilla=primera)
    segunda = services.crear_plantilla(
        actor=None, empresa=empresa, tipo_proceso=TipoProceso.INGRESO
    )
    services.publicar_plantilla(actor=None, plantilla=segunda)
    primera.refresh_from_db()
    segunda.refresh_from_db()
    assert primera.estado == "ARCHIVADA"
    assert segunda.estado == "PUBLICADA"
    assert segunda.version == 2


def test_filtro_fk_invalido_de_plantillas_devuelve_400(cliente_rrhh):
    respuesta = cliente_rrhh.get("/api/v1/onboarding/plantillas/?sector=abc")
    assert respuesta.status_code == 400
    assert "sector" in respuesta.data["campos"]


def test_no_agrega_tipo_documental_inactivo_a_un_borrador(empresa, tipo_doc):
    plantilla = services.crear_plantilla(
        actor=None,
        empresa=empresa,
        tipo_proceso=TipoProceso.INGRESO,
    )
    tipo_doc.activo = False
    tipo_doc.save(update_fields=["activo"])

    with pytest.raises(ValidationError, match="inactivo"):
        services.agregar_item(
            actor=None,
            plantilla=plantilla,
            etiqueta="Contrato",
            tipo_item=TipoItem.DOCUMENTAL,
            tipo_documento=tipo_doc,
        )


def test_no_publica_plantilla_si_un_tipo_documental_quedo_inactivo(
    empresa, tipo_doc
):
    plantilla = services.crear_plantilla(
        actor=None,
        empresa=empresa,
        tipo_proceso=TipoProceso.INGRESO,
    )
    services.agregar_item(
        actor=None,
        plantilla=plantilla,
        etiqueta="Contrato",
        tipo_item=TipoItem.DOCUMENTAL,
        tipo_documento=tipo_doc,
    )
    tipo_doc.activo = False
    tipo_doc.save(update_fields=["activo"])

    with pytest.raises(ValidationError, match="inactivo"):
        services.publicar_plantilla(actor=None, plantilla=plantilla)

    plantilla.refresh_from_db()
    assert plantilla.estado == "BORRADOR"


def test_tipo_documento_no_se_desactiva_si_una_plantilla_publicada_lo_exige(
    plantilla_con_items, tipo_doc
):
    from apps.empleados.api.serializers import TipoDocumentoSerializer

    entrada = TipoDocumentoSerializer(
        tipo_doc,
        data={"activo": False},
        partial=True,
    )
    assert entrada.is_valid() is False
    assert "publicada" in str(entrada.errors).lower()


def test_tipo_documento_no_se_desactiva_si_un_proceso_iniciado_aun_lo_necesita(
    plantilla_con_items, tipo_doc, empleado_activo
):
    from apps.empleados.api.serializers import TipoDocumentoSerializer

    proceso = services.iniciar_proceso(
        actor=None,
        relacion=empleado_activo.relacion_activa,
        tipo_proceso=TipoProceso.INGRESO,
    )
    services.archivar_plantilla(actor=None, plantilla=plantilla_con_items)

    entrada = TipoDocumentoSerializer(
        tipo_doc,
        data={"activo": False},
        partial=True,
    )
    assert proceso.items.filter(tipo_documento=tipo_doc).exists()
    assert entrada.is_valid() is False
    assert "iniciado" in str(entrada.errors).lower()


def test_version_nueva_copia_los_items_activos_de_la_publicada(empresa):
    primera = services.crear_plantilla(
        actor=None,
        empresa=empresa,
        tipo_proceso=TipoProceso.INGRESO,
    )
    services.agregar_item(
        actor=None,
        plantilla=primera,
        etiqueta="Entregar uniforme",
        tipo_item=TipoItem.ACCION,
    )
    services.publicar_plantilla(actor=None, plantilla=primera)

    segunda = services.crear_plantilla(
        actor=None,
        empresa=empresa,
        tipo_proceso=TipoProceso.INGRESO,
    )

    assert list(segunda.items.values_list("etiqueta", flat=True)) == [
        "Entregar uniforme"
    ]


# --- Reglas de dominio (services / selectors) ------------------------------------------

def test_agregar_item_documental_sin_tipo_error_amigable(empresa):
    pl = services.crear_plantilla(actor=None, empresa=empresa, tipo_proceso=TipoProceso.EGRESO)
    with pytest.raises(ValidationError):
        services.agregar_item(
            actor=None, plantilla=pl, etiqueta="X", tipo_item=TipoItem.DOCUMENTAL
        )


def test_tildar_item_documental_es_rechazado(empleado_activo, plantilla_con_items):
    proceso = services.obtener_o_crear_proceso(
        actor=None, relacion=empleado_activo.relacion_activa, tipo_proceso=TipoProceso.INGRESO
    )
    documental = proceso.items.get(tipo_item=TipoItem.DOCUMENTAL)
    with pytest.raises(ValidationError):
        services.tildar_item(actor=None, item=documental, hecho=True)


def test_documental_se_completa_al_cargar_el_documento(
    empleado_activo, plantilla_con_items, tipo_doc
):
    proceso = services.obtener_o_crear_proceso(
        actor=None, relacion=empleado_activo.relacion_activa, tipo_proceso=TipoProceso.INGRESO
    )
    # Tildo el de acción: 1 de 2.
    accion = proceso.items.get(tipo_item=TipoItem.ACCION)
    services.tildar_item(actor=None, item=accion, hecho=True)
    t = selectors.armar_tarjeta(proceso=proceso)
    assert t["progreso"] == {"hechos": 1, "total": 2, "porcentaje": 50}
    assert t["completo"] is False

    # Cargo el documento con archivo: el documental se completa SOLO, sin tilde.
    DocumentoEmpleado.objects.create(
        empleado=empleado_activo,
        relacion_laboral=empleado_activo.relacion_activa,
        tipo_documento=tipo_doc,
        archivo="documentos/fake.pdf",
    )
    t = selectors.armar_tarjeta(proceso=proceso)
    assert t["progreso"]["porcentaje"] == 100
    assert t["completo"] is True
    assert t["completado_en"] is not None


def test_documento_sin_archivo_no_completa_el_documental(
    empleado_activo, plantilla_con_items, tipo_doc
):
    proceso = services.obtener_o_crear_proceso(
        actor=None, relacion=empleado_activo.relacion_activa, tipo_proceso=TipoProceso.INGRESO
    )
    # Documento cargado pero SIN archivo adjunto: no cuenta como hecho (spec CU-29).
    DocumentoEmpleado.objects.create(
        empleado=empleado_activo,
        relacion_laboral=empleado_activo.relacion_activa,
        tipo_documento=tipo_doc,
    )
    t = selectors.armar_tarjeta(proceso=proceso)
    documental = next(i for i in t["items"] if i["tipo_item"] == TipoItem.DOCUMENTAL)
    assert documental["hecho"] is False


def test_proceso_perezoso_es_idempotente(empleado_activo, plantilla_con_items):
    rel = empleado_activo.relacion_activa
    p1 = services.obtener_o_crear_proceso(
        actor=None, relacion=rel, tipo_proceso=TipoProceso.INGRESO
    )
    p2 = services.obtener_o_crear_proceso(
        actor=None, relacion=rel, tipo_proceso=TipoProceso.INGRESO
    )
    assert p1.pk == p2.pk
    assert rel.procesos_checklist.filter(tipo_proceso=TipoProceso.INGRESO).count() == 1


def test_onboarding_prioriza_plantilla_del_sector_y_conserva_fallback_general(
    empresa, empleado_activo
):
    general = services.crear_plantilla(
        actor=None,
        empresa=empresa,
        tipo_proceso=TipoProceso.INGRESO,
    )
    services.agregar_item(
        actor=None,
        plantilla=general,
        etiqueta="Entregar credencial general",
        tipo_item=TipoItem.ACCION,
    )
    services.publicar_plantilla(actor=None, plantilla=general)
    especifica = services.crear_plantilla(
        actor=None,
        empresa=empresa,
        sector=empresa._sector_prueba,
        tipo_proceso=TipoProceso.INGRESO,
    )
    services.agregar_item(
        actor=None,
        plantilla=especifica,
        etiqueta="Entregar elementos de chofer",
        tipo_item=TipoItem.ACCION,
    )
    services.publicar_plantilla(actor=None, plantilla=especifica)

    proceso_chofer = services.iniciar_proceso(
        actor=None,
        relacion=empleado_activo.relacion_activa,
        tipo_proceso=TipoProceso.INGRESO,
    )

    assert proceso_chofer.plantilla_id == especifica.id
    assert list(proceso_chofer.items.values_list("etiqueta", flat=True)) == [
        "Entregar elementos de chofer"
    ]

    otro_sector = Sector.objects.create(nombre="Administración")
    otro_puesto = Puesto.objects.create(nombre="Administrativo", sector=otro_sector)
    administrativo = Empleado.objects.create(
        legajo="0002",
        dni="30222333",
        nombre="Ana",
        apellido="Gómez",
    )
    otra_relacion = RelacionLaboral.objects.create(
        empleado=administrativo,
        empresa=empresa,
        sector=otro_sector,
        puesto=otro_puesto,
        fecha_ingreso=timezone.localdate(),
        estado=EstadoRelacion.ACTIVA,
    )
    proceso_general = services.iniciar_proceso(
        actor=None,
        relacion=otra_relacion,
        tipo_proceso=TipoProceso.INGRESO,
    )

    assert proceso_general.plantilla_id == general.id
    assert list(proceso_general.items.values_list("etiqueta", flat=True)) == [
        "Entregar credencial general"
    ]


def test_sin_plantilla_la_tarjeta_avisa(empleado_activo):
    # No hay plantilla activa para esta empresa: el proceso nace vacío con el aviso.
    proceso = services.obtener_o_crear_proceso(
        actor=None, relacion=empleado_activo.relacion_activa, tipo_proceso=TipoProceso.INGRESO
    )
    t = selectors.armar_tarjeta(proceso=proceso)
    assert t["sin_plantilla"] is True
    assert t["progreso"]["total"] == 0


# --- API y permisos --------------------------------------------------------------------

def test_rrhh_puede_crear_plantilla_via_api(cliente_rrhh, empresa):
    resp = cliente_rrhh.post(
        "/api/v1/onboarding/plantillas/",
        {"empresa": empresa.id, "tipo_proceso": TipoProceso.INGRESO},
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert PlantillaChecklist.objects.filter(empresa=empresa).exists()


def test_empleado_no_puede_crear_plantilla(cliente_empleado, empresa):
    resp = cliente_empleado.post(
        "/api/v1/onboarding/plantillas/",
        {"empresa": empresa.id, "tipo_proceso": TipoProceso.INGRESO},
        format="json",
    )
    assert resp.status_code == 403


def test_empleado_no_puede_leer_la_configuracion_interna_de_plantillas(
    cliente_empleado, empresa
):
    services.crear_plantilla(
        actor=None,
        empresa=empresa,
        tipo_proceso=TipoProceso.INGRESO,
    )

    resp = cliente_empleado.get("/api/v1/onboarding/plantillas/")

    assert resp.status_code == 403


def test_no_hay_delete_de_plantillas(cliente_rrhh, empresa):
    pl = services.crear_plantilla(actor=None, empresa=empresa, tipo_proceso=TipoProceso.INGRESO)
    resp = cliente_rrhh.delete(f"/api/v1/onboarding/plantillas/{pl.id}/")
    assert resp.status_code == 405  # baja = PATCH activa=False, nunca DELETE


def test_tarjeta_en_ficha_y_tildado_por_rrhh(cliente_rrhh, empleado_activo, plantilla_con_items):
    url = f"/api/v1/empleados/{empleado_activo.id}/checklist/"
    previo = cliente_rrhh.get(url)
    assert previo.data["tarjeta"] is None  # GET es lectura pura
    resp = cliente_rrhh.post(
        url,
        {
            "relacion_laboral": empleado_activo.relacion_activa.id,
            "tipo_proceso": TipoProceso.INGRESO,
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    tarjeta = resp.data["tarjeta"]
    assert tarjeta["progreso"] == {"hechos": 0, "total": 2, "porcentaje": 0}

    item_accion = next(i for i in tarjeta["items"] if i["tipo_item"] == TipoItem.ACCION)
    resp = cliente_rrhh.post(
        f"{url}items/{item_accion['id']}/tildar/", {"hecho": True}, format="json"
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["tarjeta"]["progreso"]["hechos"] == 1


def test_empleado_no_puede_tildar(cliente_empleado, empleado_activo, plantilla_con_items):
    proceso = services.obtener_o_crear_proceso(
        actor=None, relacion=empleado_activo.relacion_activa, tipo_proceso=TipoProceso.INGRESO
    )
    item = proceso.items.get(tipo_item=TipoItem.ACCION)
    resp = cliente_empleado.post(
        f"/api/v1/empleados/{empleado_activo.id}/checklist/items/{item.id}/tildar/",
        {"hecho": True},
        format="json",
    )
    assert resp.status_code == 403
