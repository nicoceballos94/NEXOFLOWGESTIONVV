"""Permisos base: roles por grupo + scoping por queryset en selectors (§7)."""
from rest_framework.permissions import SAFE_METHODS, BasePermission


def usuario_tiene_rol(usuario, roles: tuple[str, ...]) -> bool:
    if not usuario or not usuario.is_authenticated:
        return False
    if usuario.is_superuser:
        return True
    return usuario.groups.filter(name__in=roles).exists()


def RolRequerido(*roles: str) -> type[BasePermission]:
    """Permiso de DRF: exige pertenecer a alguno de los grupos dados."""

    class _RolRequerido(BasePermission):
        message = f"Requiere rol: {', '.join(roles)}."

        def has_permission(self, request, view):
            return usuario_tiene_rol(request.user, roles)

    return _RolRequerido


def LecturaAutenticadaEscrituraPorRol(*roles: str) -> type[BasePermission]:
    """GET para cualquier usuario autenticado; escritura solo para los roles dados."""

    class _Permiso(BasePermission):
        message = f"La escritura requiere rol: {', '.join(roles)}."

        def has_permission(self, request, view):
            if not request.user or not request.user.is_authenticated:
                return False
            if request.method in SAFE_METHODS:
                return True
            return usuario_tiene_rol(request.user, roles)

    return _Permiso
