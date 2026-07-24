"""Contexto mínimo de la request para atribuir el origen de cada evento."""

from contextvars import ContextVar
from ipaddress import ip_address

from django.conf import settings

_ip_actual: ContextVar[str | None] = ContextVar("auditoria_ip", default=None)


def ip_actual() -> str | None:
    return _ip_actual.get()


def _ip_de_request(request) -> str | None:
    """Obtiene una IP confiable según la topología configurada.

    Por defecto usa ``REMOTE_ADDR``. En producción, Nginx Proxy Manager debe
    sobrescribir ``X-Real-IP`` y se habilita ``AUDIT_TRUST_X_FORWARDED_FOR``.
    Como respaldo se usa el último salto de ``X-Forwarded-For``: con
    ``$proxy_add_x_forwarded_for`` el cliente puede falsificar valores a la izquierda,
    pero no el ``remote_addr`` que Nginx agrega a la derecha.
    """

    def normalizada(valor) -> str | None:
        try:
            return str(ip_address(str(valor).strip()))
        except ValueError:
            return None

    if getattr(settings, "AUDIT_TRUST_X_FORWARDED_FOR", False):
        real = normalizada(request.META.get("HTTP_X_REAL_IP", ""))
        if real:
            return real
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            confiable = normalizada(forwarded.rsplit(",", 1)[-1])
            if confiable:
                return confiable
    return normalizada(request.META.get("REMOTE_ADDR", ""))


class ContextoAuditoriaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _ip_actual.set(_ip_de_request(request))
        try:
            return self.get_response(request)
        finally:
            _ip_actual.reset(token)
