#!/usr/bin/env python
"""Verifica que build.verificar_invariantes() corte ante los rediseños que debe atajar.

Por qué existe: el layout móvil vive en el canvas de Claude Design desde el 2026-07-20,
así que `build.py` ya no lo inyecta y no puede cortar por "ancla no encontrada". La red
de seguridad pasó a ser `verificar_invariantes()`, y este test es el que comprueba que
esa red efectivamente atrapa algo. Un guard sin test envejece a favor del falso verde.

El caso importante es el reordenamiento de columnas: las tarjetas móviles rotulan por
posición (`nth-child(N)::before`), así que mover una columna deja el layout impecable y
las etiquetas mintiendo. Eso no lo detecta ningún chequeo de "existe la clase".

Uso:  python frontend/tests/test_invariantes_diseno.py
"""
import contextlib
import importlib.util
import io
import pathlib
import sys

FRONTEND = pathlib.Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("buildpy", FRONTEND / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

BUENO = (FRONTEND / "design" / "Ceibo RRHH.dc.html").read_text(encoding="utf-8")


def corre(html):
    """Corre el guard sobre `html`. Devuelve (corto, salida)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            build.verificar_invariantes(html)
        return False, buf.getvalue()
    except SystemExit as e:
        return True, buf.getvalue() + str(e)


# (nombre, html mutado, debe_cortar)
CASOS = [
    (
        "el diseño actual del repo",
        BUENO,
        False,
    ),
    (
        "se reordenan dos columnas de Empleados",
        BUENO.replace("<div>EMPRESA</div><div>SECTOR</div>",
                      "<div>SECTOR</div><div>EMPRESA</div>"),
        True,
    ),
    (
        "se agrega una columna a Novedades",
        BUENO.replace("<div>TIPO</div><div>EMPLEADO</div>",
                      "<div>TIPO</div><div>LEGAJO</div><div>EMPLEADO</div>"),
        True,
    ),
    (
        "se renombra una columna",
        BUENO.replace("<div>CLASIFICACIÓN</div>", "<div>MOTIVO</div>"),
        True,
    ),
    (
        "el rediseño quita la clase de la fila de Novedades",
        BUENO.replace('class="ceibo-nov-row" ', ""),
        True,
    ),
    (
        "el rediseño borra el bloque @media de Empleados",
        BUENO.replace(".ceibo-emp-head{display:none !important}", ""),
        True,
    ),
    (
        "se renombra la regla del menú (.ceibo-navlbl → .ceibo-navlbl-x)",
        BUENO.replace(".ceibo-navlbl,.ceibo-brandlbl,.ceibo-userlbl{position:absolute !important",
                      ".ceibo-navlbl-x,.ceibo-brandlbl,.ceibo-userlbl{position:absolute !important"),
        True,
    ),
    (
        "el menú vuelve a display:none (regresión de REG-03)",
        BUENO.replace(
            ".ceibo-navlbl,.ceibo-brandlbl,.ceibo-userlbl{position:absolute !important;width:1px !important",
            ".ceibo-navlbl,.ceibo-brandlbl,.ceibo-userlbl{display:none !important;width:1px !important"),
        True,
    ),
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # consola Windows (cp1252) → UTF-8
    except Exception:
        pass

    ok = True
    for nombre, html, debe_cortar in CASOS:
        # Si un reemplazo no encontró su texto, el caso probaría el diseño sano y pasaría
        # en verde sin verificar nada: eso es un test roto, no un test que pasa.
        if debe_cortar and html == BUENO:
            print(f"  [ROTO ] {nombre}: el reemplazo no aplicó; ¿cambió el diseño?")
            ok = False
            continue
        corto, salida = corre(html)
        bien = corto == debe_cortar
        ok &= bien
        print(f"  [{'OK   ' if bien else 'FALLA'}] {nombre} → {'corta' if corto else 'pasa'}")
        if not bien:
            print("        salida del guard:")
            for linea in salida.splitlines():
                print(f"        {linea}")

    print("\n" + ("OK: el guard corta en todos los rediseños peligrosos."
                  if ok else "FALLA: el guard no protege lo que dice proteger."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
