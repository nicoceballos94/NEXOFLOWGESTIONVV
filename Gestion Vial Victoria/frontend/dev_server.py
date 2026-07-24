#!/usr/bin/env python
"""Servidor local same-origin: estáticos de dist/ + proxy /api/ a Django.

No es un servidor de producción. Uso:
    python dev_server.py
    # CEIBO_BACKEND=http://127.0.0.1:8000 CEIBO_PORT=8080 python dev_server.py
"""
from functools import partial
from http.client import HTTPConnection
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import urlsplit

RAIZ = Path(__file__).resolve().parent
DIST = RAIZ / "dist"
BACKEND = urlsplit(os.environ.get("CEIBO_BACKEND", "http://127.0.0.1:8000"))
PUERTO = int(os.environ.get("CEIBO_PORT", "8080"))
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

if BACKEND.scheme != "http" or not BACKEND.hostname:
    raise SystemExit("CEIBO_BACKEND debe ser una URL http válida para desarrollo local.")


class Handler(SimpleHTTPRequestHandler):
    def _es_api(self):
        return self.path == "/api" or self.path.startswith("/api/")

    def _proxy_api(self):
        host_frontend = self.headers.get("Host", "")
        hostname_frontend = urlsplit(f"//{host_frontend}").hostname
        if hostname_frontend not in {"127.0.0.1", "localhost"}:
            self.send_error(400, "Host local inválido")
            return
        largo = int(self.headers.get("Content-Length", "0") or "0")
        cuerpo = self.rfile.read(largo) if largo else None
        headers = {
            clave: valor
            for clave, valor in self.headers.items()
            if clave.lower() not in HOP_BY_HOP
            and clave.lower() not in {"host", "content-length"}
        }
        # HTTPConnection elige el backend por separado; el Host debe seguir siendo el
        # origen visible del frontend. Así Django compara Origin/Host correctamente para
        # CSRF, igual que detrás del gateway de producción.
        headers["Host"] = host_frontend
        headers["X-Forwarded-Host"] = host_frontend
        headers["X-Forwarded-Proto"] = "http"
        conexion = HTTPConnection(BACKEND.hostname, BACKEND.port or 80, timeout=30)
        try:
            conexion.request(self.command, self.path, body=cuerpo, headers=headers)
            respuesta = conexion.getresponse()
            self.send_response(respuesta.status, respuesta.reason)
            for clave, valor in respuesta.getheaders():
                if clave.lower() not in HOP_BY_HOP and clave.lower() not in {"server", "date"}:
                    self.send_header(clave, valor)
            self.end_headers()
            if self.command != "HEAD":
                while True:
                    bloque = respuesta.read(64 * 1024)
                    if not bloque:
                        break
                    self.wfile.write(bloque)
        finally:
            conexion.close()

    def do_GET(self):
        self._proxy_api() if self._es_api() else super().do_GET()

    def do_HEAD(self):
        self._proxy_api() if self._es_api() else super().do_HEAD()

    def do_POST(self):
        self._proxy_api() if self._es_api() else self.send_error(405)

    def do_PUT(self):
        self._proxy_api() if self._es_api() else self.send_error(405)

    def do_PATCH(self):
        self._proxy_api() if self._es_api() else self.send_error(405)

    def do_DELETE(self):
        self._proxy_api() if self._es_api() else self.send_error(405)

    def do_OPTIONS(self):
        self._proxy_api() if self._es_api() else self.send_error(405)


def main():
    if not (DIST / "index.html").exists():
        raise SystemExit("Falta dist/index.html. Ejecutá primero: python build.py")
    servidor = ThreadingHTTPServer(
        ("127.0.0.1", PUERTO),
        partial(Handler, directory=str(DIST)),
    )
    print(f"Ceibo: http://127.0.0.1:{PUERTO}")
    print(f"API:   {BACKEND.geturl()}/api/ (proxy same-origin)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
