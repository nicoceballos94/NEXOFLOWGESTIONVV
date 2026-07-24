from django.contrib.auth import logout
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import AuthenticationFailed

from common import roles


class SessionAuthentication401(SessionAuthentication):
    """Sesión humana + CSRF, conservando 401 cuando no hay identidad utilizable.

    ``Servicio`` está reservado para credenciales M2M futuras. La comprobación se hace
    en cada request —no solo al iniciar sesión— para cerrar también una sesión que ya
    existía si a la cuenta se le asignó después ese rol por error.
    """

    def authenticate(self, request):
        resultado = super().authenticate(request)
        if resultado is None:
            return None

        usuario, autenticador = resultado
        if usuario.groups.filter(name=roles.SERVICIO).exists():
            # Revoca la sesión comprometida en vez de devolver 401 indefinidamente con
            # una cookie todavía válida. ``request._request`` es el HttpRequest de Django.
            logout(request._request)
            raise AuthenticationFailed(
                "Las identidades de Servicio no pueden usar sesiones humanas."
            )
        return usuario, autenticador

    def authenticate_header(self, request):
        return "Session"
