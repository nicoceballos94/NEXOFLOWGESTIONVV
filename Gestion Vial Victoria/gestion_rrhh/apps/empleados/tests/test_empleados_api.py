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
        {"tipo_documento": tipo.id, "archivo": _archivo("viejo.pdf", b"apto 2025")},
        format="multipart",
    ).data["id"]
    ruta_vieja = media_temporal / DocumentoEmpleado.objects.get(pk=doc_id).archivo.name
    assert ruta_vieja.exists()

    with django_capture_on_commit_callbacks(execute=True):
        resp = cliente_rrhh.patch(
            f"/api/v1/empleados/{empleado.id}/documentos/{doc_id}/",
            {"archivo": _archivo("nuevo.pdf", b"apto 2026"), "fecha_vencimiento": "2027-06-01"},
            format="multipart",
        )
    assert resp.status_code == 200, resp.data

    doc = DocumentoEmpleado.objects.get(pk=doc_id)
    assert not ruta_vieja.exists(), "el scan viejo quedó huérfano en MEDIA_ROOT"
    assert (media_temporal / doc.archivo.name).read_bytes() == b"apto 2026"


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
