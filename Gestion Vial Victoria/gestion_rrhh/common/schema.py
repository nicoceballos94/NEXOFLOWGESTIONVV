"""Extensiones del contrato OpenAPI compartidas por toda la API."""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionCookieAuthenticationScheme(OpenApiAuthenticationExtension):
    """Documenta la sesión humana que Django transporta en cookie HttpOnly."""

    target_class = "common.authentication.SessionAuthentication401"
    name = "cookieAuth"
    priority = 1

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": "sessionid",
            "description": (
                "Cookie de sesión HttpOnly. Las escrituras requieren además el "
                "header X-CSRFToken obtenido de la cookie csrftoken."
            ),
        }
