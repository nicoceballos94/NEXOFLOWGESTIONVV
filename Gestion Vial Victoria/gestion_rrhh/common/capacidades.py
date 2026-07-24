"""Matriz de capacidades por rol (§7): única fuente de qué acciones habilita cada rol.

El backend ya decide *si* una acción procede en `common/permissions.py` (devuelve 403).
Esto NO reemplaza eso: traduce el mismo criterio a un dict de booleanos que el front
consume para **esconder** los botones que el rol no puede usar. Es honestidad visual, no
seguridad —el 403 sigue estando—.

Vive al lado de `roles.py` a propósito: cada clave espeja una permission class existente,
y ambos usan las mismas constantes de rol. El test de contrato
(`apps/usuarios/tests/test_capacidades.py`) afirma que esta matriz y los permisos reales
no se separen.
"""
from common import roles

# Grupos de roles, nombrados igual que las permission classes que espejan (permissions.py
# los arma con RolRequerido/LecturaAutenticadaEscrituraPorRol sobre estas mismas tuplas).
_OPERATIVOS = (roles.ADMIN, roles.RRHH, roles.SUPERVISOR)  # cargar/prorrogar/editar
_SOLO_RRHH = (roles.ADMIN, roles.RRHH)  # R11 y escritura de fichas/catálogos/config
# La bitácora es el único permiso que NO incluye a RRHH: es el rol que más aparece
# auditado (altas, bajas, aprobaciones), y no se le da a nadie su propio expediente.
_SOLO_ADMIN = (roles.ADMIN,)


def capacidades_de(usuario) -> dict[str, bool]:
    """rol → capacidades. Falla cerrada: sin usuario autenticado, todo en False.

    | clave               | roles                    | espeja a                          |
    |---------------------|--------------------------|-----------------------------------|
    | ve_dotacion         | Admin/RRHH/Supervisor    | _VeDotacion / _puede_ver_dotacion |
    | empleados_escribir  | Admin/RRHH               | _SoloRRHH (empleados)             |
    | novedades_cargar    | Admin/RRHH/Supervisor    | _Operativos (novedades)           |
    | novedades_decidir   | Admin/RRHH               | _SoloRRHH (aprobar/rechazar/anular)|
    | catalogos_escribir  | Admin/RRHH               | organización (escritura)          |
    | config_escribir     | Admin/RRHH               | config vencimientos (escritura)   |
    | reportes_ver        | Admin/RRHH               | reportes históricos               |
    | auditoria_ver       | Admin                    | _SoloAdmin (bitácora)             |
    """
    if usuario is None or not usuario.is_authenticated:
        return {clave: False for clave in _CLAVES}
    if usuario.groups.filter(name=roles.SERVICIO).exists():
        return {clave: False for clave in _CLAVES}
    return {
        "ve_dotacion": usuario.tiene_rol(*_OPERATIVOS),
        "empleados_escribir": usuario.tiene_rol(*_SOLO_RRHH),
        "novedades_cargar": usuario.tiene_rol(*_OPERATIVOS),
        "novedades_decidir": usuario.tiene_rol(*_SOLO_RRHH),
        "catalogos_escribir": usuario.tiene_rol(*_SOLO_RRHH),
        "config_escribir": usuario.tiene_rol(*_SOLO_RRHH),
        "reportes_ver": usuario.tiene_rol(*_SOLO_RRHH),
        "auditoria_ver": usuario.tiene_rol(*_SOLO_ADMIN),
    }


# Orden de claves, para el caso "todo en False" y para que los consumidores sepan el set.
_CLAVES = (
    "ve_dotacion",
    "empleados_escribir",
    "novedades_cargar",
    "novedades_decidir",
    "catalogos_escribir",
    "config_escribir",
    "reportes_ver",
    "auditoria_ver",
)
