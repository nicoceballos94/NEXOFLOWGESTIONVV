"""Contrato de capacidades (A5): la matriz que anuncia /mi/perfil/ debe coincidir con
lo que el backend realmente permite. Si `common/capacidades.py` y `common/permissions.py`
se separan, este test se pone rojo —que es exactamente el drift que queremos evitar—.
"""
import pytest
from rest_framework.test import APIClient

from common import roles

pytestmark = pytest.mark.django_db

# Capacidades esperadas por rol. Es la fuente humana del contrato: si cambia el diseño de
# permisos, se actualiza acá a conciencia y el test valida que el código la respete.
ESPERADO = {
    roles.ADMIN: {
        "ve_dotacion": True, "empleados_escribir": True, "novedades_cargar": True,
        "novedades_decidir": True, "catalogos_escribir": True, "config_escribir": True,
    },
    roles.RRHH: {
        "ve_dotacion": True, "empleados_escribir": True, "novedades_cargar": True,
        "novedades_decidir": True, "catalogos_escribir": True, "config_escribir": True,
    },
    roles.SUPERVISOR: {
        "ve_dotacion": True, "empleados_escribir": False, "novedades_cargar": True,
        "novedades_decidir": False, "catalogos_escribir": False, "config_escribir": False,
    },
    roles.EMPLEADO: {
        "ve_dotacion": False, "empleados_escribir": False, "novedades_cargar": False,
        "novedades_decidir": False, "catalogos_escribir": False, "config_escribir": False,
    },
    roles.SERVICIO: {
        "ve_dotacion": False, "empleados_escribir": False, "novedades_cargar": False,
        "novedades_decidir": False, "catalogos_escribir": False, "config_escribir": False,
    },
}

# Un endpoint por capacidad. La regla del contrato: si el rol TIENE la capacidad, el
# endpoint NO devuelve 403 (da 200/400/404 según payload); si NO la tiene, da 403.
# Los cuerpos van vacíos a propósito: no probamos la lógica del endpoint, solo la puerta
# del permiso, que DRF evalúa antes de validar el cuerpo o resolver el objeto.
PROBES = {
    "ve_dotacion": ("get", "/api/v1/dashboard/metricas/", None),
    "empleados_escribir": ("post", "/api/v1/empleados/", {}),
    "novedades_cargar": ("post", "/api/v1/novedades/", {}),
    # aprobar es detail=True: con id inexistente, el permiso corre ANTES del get_object,
    # así que sin permiso da 403 y con permiso llega a 404. En ambos casos != 403 ⟺ tiene.
    "novedades_decidir": ("post", "/api/v1/novedades/999999/aprobar/", {}),
    "catalogos_escribir": ("post", "/api/v1/empresas/", {}),
    "config_escribir": ("patch", "/api/v1/config/vencimientos/", {}),
}


def _cliente(crear_usuario, rol):
    usuario = crear_usuario(username=f"demo_{rol.lower()}", rol=rol)
    c = APIClient()
    c.force_authenticate(usuario)
    return c


@pytest.mark.parametrize("rol", list(ESPERADO))
def test_perfil_anuncia_capacidades_esperadas(crear_usuario, rol):
    """/mi/perfil/ devuelve el objeto capacidades correcto para el rol."""
    c = _cliente(crear_usuario, rol)
    resp = c.get("/api/v1/mi/perfil/")
    assert resp.status_code == 200
    assert resp.data["capacidades"] == ESPERADO[rol]


@pytest.mark.parametrize("rol", list(ESPERADO))
def test_capacidades_coinciden_con_permisos_reales(crear_usuario, rol):
    """El contrato: cada capacidad anunciada coincide con el 403/no-403 real del endpoint."""
    c = _cliente(crear_usuario, rol)
    capacidades = c.get("/api/v1/mi/perfil/").data["capacidades"]

    for clave, (metodo, url, cuerpo) in PROBES.items():
        kwargs = {"format": "json"} if cuerpo is not None else {}
        if cuerpo is not None:
            resp = getattr(c, metodo)(url, cuerpo, **kwargs)
        else:
            resp = getattr(c, metodo)(url)
        tiene_permiso_real = resp.status_code != 403
        assert capacidades[clave] == tiene_permiso_real, (
            f"rol {rol}: capacidad {clave}={capacidades[clave]} pero "
            f"{metodo.upper()} {url} devolvió {resp.status_code} "
            f"(tiene_permiso_real={tiene_permiso_real})"
        )
