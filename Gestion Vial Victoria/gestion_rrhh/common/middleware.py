"""Cabeceras transversales para respuestas que contienen datos de RRHH."""


class NoCacheAPIMiddleware:
    """Evita que navegadores o proxies compartidos conserven PII de la API."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response
