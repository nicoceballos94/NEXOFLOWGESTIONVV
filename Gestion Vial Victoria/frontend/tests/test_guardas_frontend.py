#!/usr/bin/env python
"""Prueba las guardas de sesión, seguridad, identidad y transiciones del frontend.

Uso: python frontend/tests/test_guardas_frontend.py
"""
import contextlib
import importlib.util
import io
import pathlib
import sys

FRONTEND = pathlib.Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("buildpy_guardas", FRONTEND / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

DISENO = (FRONTEND / "design" / "Ceibo RRHH.dc.html").read_text(encoding="utf-8")
INTEGRACION = (FRONTEND / "integration" / "ceibo-api.js").read_text(encoding="utf-8")
DEV_SERVER = (FRONTEND / "dev_server.py").read_text(encoding="utf-8")


def construir_en_memoria():
    salida = io.StringIO()
    with contextlib.redirect_stdout(salida):
        return build.aplicar_ediciones(DISENO)


HTML = construir_en_memoria()


def corre(html, integracion):
    salida = io.StringIO()
    try:
        with contextlib.redirect_stdout(salida):
            build.verificar_guardas_frontend(html, integracion)
        return False, salida.getvalue()
    except SystemExit as error:
        return True, salida.getvalue() + str(error)


CASOS = [
    ("artefacto actual", HTML, INTEGRACION, False),
    (
        "regresa la API localhost",
        HTML,
        INTEGRACION.replace('API: "/api/v1"', 'API: "http://localhost:8000/api/v1"'),
        True,
    ),
    (
        "se elimina el control de origen",
        HTML,
        INTEGRACION.replace("url.origin !== window.location.origin", "false"),
        True,
    ),
    (
        "vuelve una sesión JWT",
        HTML,
        INTEGRACION + '\nvar _token = ""; var _refresh = ""; // Bearer Authorization /auth/token/\n',
        True,
    ),
    (
        "se persiste la sesión en sessionStorage",
        HTML,
        INTEGRACION + '\nsessionStorage.setItem("sesion", "credencial");\n',
        True,
    ),
    (
        "se cachea el CSRF de las mutaciones",
        HTML,
        INTEGRACION.replace(
            'opts.headers["X-CSRFToken"] = csrfActual();',
            'opts.headers["X-CSRFToken"] = csrfCacheado;',
        ),
        True,
    ),
    (
        "se pierde el retorno a login ante 401",
        HTML,
        INTEGRACION.replace("notificarSesionVencida();", "limpiarSesion();"),
        True,
    ),
    (
        "un nombre vuelve a innerHTML",
        HTML,
        INTEGRACION.replace(
            "o.textContent = etiquetaEmpleado(e)",
            "dl.innerHTML = _rawEmpleados",
        ),
        True,
    ),
    (
        "la ficha vuelve a inventar el legajo",
        HTML.replace("v:raw.legajo||'—'", "v:'LEG-'+String(raw.id)"),
        INTEGRACION,
        True,
    ),
    (
        "la ficha vuelve a unir novedades por nombre",
        HTML.replace(
            "String(n._empId)===String(raw.id)",
            "n.emp===raw.name",
        ),
        INTEGRACION,
        True,
    ),
    (
        "la ficha vuelve a romperse con un alcance sin empleados",
        HTML.replace("name:'Sin empleados asignados'", "name:'Sin selección'"),
        INTEGRACION,
        True,
    ),
    (
        "el detalle vuelve a romperse con un alcance sin novedades",
        HTML.replace("tipo:'Sin novedades disponibles'", "tipo:'Sin selección'"),
        INTEGRACION,
        True,
    ),
    (
        "la autoconsulta vuelve a abrir un Dashboard prohibido",
        HTML.replace(
            "const veDotacion = window.CeiboAPI.puede('ve_dotacion');",
            "const veDotacion = true;",
        ),
        INTEGRACION,
        True,
    ),
    (
        "Dashboard vuelve a mostrarse sin alcance de dotación",
        HTML.replace(
            '<sc-if value="{{ puedeDotacion }}" hint-placeholder-val="{{ true }}">\n'
            '        <button type="button" onClick="{{ goDash }}"',
            '<button type="button" onClick="{{ goDash }}"',
        ),
        INTEGRACION,
        True,
    ),
    (
        "Alertas vuelve a mostrarse sin alcance de dotación",
        HTML.replace(
            '<sc-if value="{{ puedeDotacion }}" hint-placeholder-val="{{ true }}">\n'
            '        <button type="button" onClick="{{ goAle }}"',
            '<button type="button" onClick="{{ goAle }}"',
        ),
        INTEGRACION,
        True,
    ),
    (
        "Configuración vuelve a mostrarse sin capacidad",
        HTML.replace(
            '<sc-if value="{{ puedeConfig }}" hint-placeholder-val="{{ true }}">\n'
            '        <button type="button" onClick="{{ goCfg }}"',
            '<button type="button" onClick="{{ goCfg }}"',
        ),
        INTEGRACION,
        True,
    ),
    (
        "el alta vuelve a separar el nombre por heurística",
        HTML,
        INTEGRACION.replace(
            'nombre: g("nombre"), apellido: g("apellido")',
            'nombre: splitName(g("nombre y apellido")).nombre, apellido: ""',
        ),
        True,
    ),
    (
        "el alta intenta simular Cerrada",
        HTML,
        INTEGRACION.replace(
            'var ESTADONOV = { "Aprobada": "aprobar",',
            'var ESTADONOV = { "Cerrada": "cerrar", "Aprobada": "aprobar",',
        ),
        True,
    ),
    (
        "desaparece Tomar del detalle",
        HTML.replace('onClick="{{ tomarNov }}"', 'onClick="{{ aprobarNov }}"'),
        INTEGRACION,
        True,
    ),
    (
        "desaparece Cerrar de las prórrogas",
        HTML.replace('onClick="{{ t.doCerrar }}"', 'onClick="{{ t.doAprobar }}"'),
        INTEGRACION,
        True,
    ),
    (
        "rechazo vuelve a enviarse sin motivo",
        HTML,
        INTEGRACION.replace("body.motivo = motivo;", "body = {};"),
        True,
    ),
    (
        "puesto vuelve a resolverse globalmente",
        HTML,
        INTEGRACION.replace(
            "_puestoBySectorNombre[clavePuesto(sectorId, nombre)]",
            "_puestoByName[nombre]",
        ),
        True,
    ),
    (
        "la ficha deja de pedir el detalle auditado",
        HTML,
        INTEGRACION.replace(
            'await jget("/empleados/" + id + "/")',
            'await getAllPages("/empleados/?id=" + id)',
        ),
        True,
    ),
    (
        "reingreso vuelve a buscar el DNI en el listado",
        HTML,
        INTEGRACION.replace(
            'jget("/empleados/por-dni/?dni="',
            'getAllPages("/empleados/?dni="',
        ),
        True,
    ),
    (
        "reingreso vuelve a omitir el sector",
        HTML.replace('data-reingreso="sector"', 'data-reingreso="sector-omitido"'),
        INTEGRACION,
        True,
    ),
    (
        "checklist vuelve a iniciarse sin acción explícita",
        HTML.replace('onClick="{{ fichaChk.iniciar }}"', 'onClick="{{ closeModal }}"'),
        INTEGRACION,
        True,
    ),
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ok = True
    for nombre, html, integracion, debe_cortar in CASOS:
        corto, salida = corre(html, integracion)
        bien = corto == debe_cortar
        ok &= bien
        print(f"  [{'OK   ' if bien else 'FALLA'}] {nombre} → {'corta' if corto else 'pasa'}")
        if not bien:
            for linea in salida.splitlines():
                print(f"        {linea}")
    # El guard de producción corre sobre el artefacto ya hasheado: cubre el runtime derivado,
    # las dependencias vendorizadas y la ausencia de JavaScript inline/CDN.
    salida = io.StringIO()
    html_prod = HTML
    try:
        with contextlib.redirect_stdout(salida):
            html_prod = build.escribir_assets(HTML)
            build.verificar_artefacto_produccion(html_prod)
        prod_ok = True
    except SystemExit:
        prod_ok = False
    ok &= prod_ok
    print(f"  [{'OK   ' if prod_ok else 'FALLA'}] artefacto CSP de producción → {'pasa' if prod_ok else 'corta'}")

    salida = io.StringIO()
    try:
        with contextlib.redirect_stdout(salida):
            build.verificar_artefacto_produccion(
                html_prod + '<script>window.regresion=true</script>'
            )
        inline_corta = False
    except SystemExit:
        inline_corta = True
    ok &= inline_corta
    print(f"  [{'OK   ' if inline_corta else 'FALLA'}] vuelve JavaScript inline → {'corta' if inline_corta else 'pasa'}")

    proxy_local_ok = all(
        fragmento in DEV_SERVER
        for fragmento in (
            'hostname_frontend not in {"127.0.0.1", "localhost"}',
            'headers["Host"] = host_frontend',
            'headers["X-Forwarded-Host"] = host_frontend',
        )
    ) and 'headers["Host"] = BACKEND.netloc' not in DEV_SERVER
    ok &= proxy_local_ok
    print(
        f"  [{'OK   ' if proxy_local_ok else 'FALLA'}] "
        "proxy local conserva Origin/Host para CSRF y rechaza DNS rebinding"
    )
    print(
        "\n"
        + (
            "OK: las guardas bloquean regresiones de sesión, seguridad, identidad y flujo."
            if ok
            else "FALLA: una guarda no protege lo que declara."
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
