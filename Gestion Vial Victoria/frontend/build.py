#!/usr/bin/env python
"""Arma el frontend desplegable inyectando el cableado al backend en el diseño.

El diseño (`design/*.dc.html`) se baja de Claude Design y NO se edita a mano.
Este script le aplica inyecciones deterministas (shims delgados que llaman a
`window.CeiboAPI.*`, definido en `integration/ceibo-api.js`) y escribe `dist/`.

Si el diseño cambia (rediseño en Claude Design), se vuelve a bajar y se corre
`python build.py`. Cada inyección falla ruidosamente si no encuentra su ancla,
así un cambio de diseño que rompa un anclaje se detecta al instante.

Uso:  python build.py   →   dist/index.html + support.js + ceibo-api.js
Servir: cd dist && python -m http.server 8080
"""
from pathlib import Path
import shutil
import sys

RAIZ = Path(__file__).resolve().parent
DESIGN = RAIZ / "design"
DIST = RAIZ / "dist"
SRC = DESIGN / "Ceibo RRHH.dc.html"  # el canvas que se edita en Claude Design (fuente de verdad)

# Bloque de métodos que se inyecta en la clase Component (reemplaza confirmReingreso).
BLOQUE_INTEGRACION = r"""  // ===== integración con el backend (inyectado por build.py) =====
  reloadEmpleados = async () => {
    const emps = await window.CeiboAPI.listEmpleados();
    this.setState({ empleados: emps });
  };
  reloadNovedades = async () => {
    const novs = await window.CeiboAPI.listNovedades();
    this.setState({ novedades: novs });
  };
  async componentDidMount() {
    try {
      await window.CeiboAPI.init();
      await this.reloadEmpleados();
      await this.reloadNovedades();
      const e = this.state.empleados;
      if (e && e.length) this.setState({ selEmp: e[0].id });
    } catch (err) {
      console.error('[ceibo] init', err);
      this.setState({ apiErr: String(err) });
    }
  }
  renderVals() {
    const v = this.renderValsBase();
    v.submitAlta = this.submitAlta;
    v.altaTitle = this.state.altaEditId ? 'Editar empleado' : 'Alta de empleado';
    if (v.ficha) v.ficha.openEdit = () => this.openEdit(this.state.selEmp);
    v.submitNov = this.submitNov;
    v.submitProrroga = this.submitProrroga;
    return v;
  }
  openAltaNov = () => {
    this.setState({ modal: 'altanov' });
    setTimeout(() => window.CeiboAPI.populateNovForm(), 60);
  };
  submitNov = async () => {
    try {
      await window.CeiboAPI.submitNov();
      this.setState({ modal: null });
      await this.reloadNovedades();
    } catch (e) { console.error('[ceibo] novedad', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  submitProrroga = async () => {
    try {
      await window.CeiboAPI.submitProrroga(this.state.detNovId);
      this.setState({ modal: null });
      await this.reloadNovedades();
    } catch (e) { console.error('[ceibo] prórroga', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  openAlta = () => this.setState({ modal: 'alta', altaEditId: null });
  openEdit = (id) => {
    this.setState({ modal: 'alta', altaEditId: id });
    const emp = (this.state.empleados || []).find(e => e.id === id);
    setTimeout(() => window.CeiboAPI.prefillAlta(emp), 60);
  };
  submitAlta = async () => {
    try {
      await window.CeiboAPI.submitAlta(this.state.altaEditId, this.state.selEmp);
      this.setState({ modal: null, altaEditId: null });
      await this.reloadEmpleados();
    } catch (e) { console.error('[ceibo] alta/edición', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  confirmBaja = async () => {
    try {
      const emp = (this.state.empleados || []).find(e => e.id === this.state.bajaId);
      await window.CeiboAPI.darDeBaja(emp);
      this.setState({ modal: null });
      await this.reloadEmpleados();
    } catch (e) { console.error('[ceibo] baja', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  confirmReingreso = async (id) => {
    try {
      const emp = (this.state.empleados || []).find(e => e.id === id);
      await window.CeiboAPI.reingreso(emp);
      await this.reloadEmpleados();
    } catch (e) { console.error('[ceibo] reingreso', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  selectEmp = (id) => {
    this.setState({ selEmp: id, view: 'ficha' });
    const self = this;
    window.CeiboAPI.loadDocs(id).then(function (docs) {
      self.setState(function (s) {
        return { empleados: (s.empleados || []).map(function (e) { return e.id === id ? Object.assign({}, e, { docs: docs }) : e; }) };
      });
    }).catch(function () {});
  };
}
"""

# (ancla_a_buscar, texto_de_reemplazo, descripción). Cada ancla debe existir 1+ vez.
EDICIONES = [
    # --- head: cargar la capa de integración ---
    (
        '<script src="./support.js"></script>',
        '<script src="./support.js"></script>\n<script src="./ceibo-api.js"></script>',
        "head: script ceibo-api.js",
    ),
    # --- state: campos nuevos ---
    (
        "theme: 'dark', view: 'dashboard', selEmp: 1,",
        "theme: 'dark', view: 'dashboard', selEmp: 1,\n    empleados: null, novedades: null, apiErr: null, altaEditId: null,",
        "state: campos de integración",
    ),
    # --- novBase(): usar datos reales si están cargados ---
    (
        "  novBase() {\n    return [",
        "  novBase() {\n    if (this.state.novedades) return this.state.novedades;\n    return [",
        "novBase(): guard de datos reales",
    ),
    # --- base(): usar datos reales si están cargados ---
    (
        "  base() {\n    return [",
        "  base() {\n    if (this.state.empleados) return this.state.empleados;\n    return [",
        "base(): guard de datos reales",
    ),
    # --- renderVals → renderValsBase (para poder envolverlo) ---
    (
        "  renderVals(){",
        "  renderValsBase(){",
        "renderVals → renderValsBase",
    ),
    # --- inyectar métodos de integración (reemplaza confirmReingreso + cierre de clase) ---
    (
        "  confirmReingreso = (id)=> this.setState(s=>({bajaSet:s.bajaSet.filter(x=>x!==id)}));\n}",
        BLOQUE_INTEGRACION,
        "clase: bloque de integración",
    ),
    # --- template: marcar modales para leer sus inputs del DOM ---
    (
        "style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:720px;max-width:100%",
        "data-modal=\"alta\" style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:720px;max-width:100%",
        "modal alta: data-modal",
    ),
    (
        "style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:440px;max-width:100%",
        "data-modal=\"baja\" style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:440px;max-width:100%",
        "modal baja: data-modal",
    ),
    (
        "style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:680px;max-width:100%",
        "data-modal=\"altanov\" style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:680px;max-width:100%",
        "modal alta novedad: data-modal",
    ),
    (
        "style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:460px;max-width:100%",
        "data-modal=\"prorroga\" style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:460px;max-width:100%",
        "modal prórroga: data-modal",
    ),
    # --- template: botón Guardar empleado → submitAlta ---
    (
        '<button onClick="{{ closeModal }}" style="background:var(--accent);border:none;color:#04201C;font-weight:600;font-size:13px;border-radius:10px;padding:0 20px;height:40px;cursor:pointer;box-shadow:0 4px 14px rgba(45,212,191,.28)">Guardar empleado</button>',
        '<button onClick="{{ submitAlta }}" style="background:var(--accent);border:none;color:#04201C;font-weight:600;font-size:13px;border-radius:10px;padding:0 20px;height:40px;cursor:pointer;box-shadow:0 4px 14px rgba(45,212,191,.28)">Guardar empleado</button>',
        "botón Guardar → submitAlta",
    ),
    # --- template: botón Registrar novedad → submitNov ---
    (
        '<button onClick="{{ closeModal }}" style="background:var(--accent);border:none;color:#04201C;font-weight:600;font-size:13px;border-radius:10px;padding:0 20px;height:40px;cursor:pointer">Registrar</button>',
        '<button onClick="{{ submitNov }}" style="background:var(--accent);border:none;color:#04201C;font-weight:600;font-size:13px;border-radius:10px;padding:0 20px;height:40px;cursor:pointer">Registrar</button>',
        "botón Registrar novedad → submitNov",
    ),
    # --- template: botón Registrar prórroga → submitProrroga ---
    (
        '<button onClick="{{ backToDet }}" style="background:var(--accent);border:none;color:#04201C;font-weight:600;font-size:13px;border-radius:10px;padding:0 20px;height:40px;cursor:pointer">Registrar prórroga</button>',
        '<button onClick="{{ submitProrroga }}" style="background:var(--accent);border:none;color:#04201C;font-weight:600;font-size:13px;border-radius:10px;padding:0 20px;height:40px;cursor:pointer">Registrar prórroga</button>',
        "botón Registrar prórroga → submitProrroga",
    ),
    # --- template: título del modal dinámico (Alta / Editar) ---
    (
        'font-size:17px;color:var(--text)">Alta de empleado</div>',
        'font-size:17px;color:var(--text)">{{ altaTitle }}</div>',
        "título modal dinámico",
    ),
    # --- template: botón Editar → ficha.openEdit ---
    (
        '<button style="display:flex;align-items:center;gap:7px;background:var(--surface2);color:var(--text);font-weight:600;font-size:13px;border:1px solid var(--border2);border-radius:10px;padding:0 15px;height:38px;cursor:pointer" style-hover="border-color:var(--text3)">',
        '<button onClick="{{ ficha.openEdit }}" style="display:flex;align-items:center;gap:7px;background:var(--surface2);color:var(--text);font-weight:600;font-size:13px;border:1px solid var(--border2);border-radius:10px;padding:0 15px;height:38px;cursor:pointer" style-hover="border-color:var(--text3)">',
        "botón Editar → openEdit",
    ),
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # consola Windows (cp1252) → UTF-8
    except Exception:
        pass
    if not SRC.exists():
        sys.exit(f"ERROR: no está el diseño en {SRC}")
    html = SRC.read_text(encoding="utf-8")

    for ancla, reemplazo, desc in EDICIONES:
        if ancla not in html:
            sys.exit(f"ERROR: ancla no encontrada [{desc}]. ¿Cambió el diseño? Revisar build.py")
        html = html.replace(ancla, reemplazo, 1)
        print("  [ok] "+desc)

    DIST.mkdir(exist_ok=True)
    (DIST / "index.html").write_text(html, encoding="utf-8")
    shutil.copy2(DESIGN / "support.js", DIST / "support.js")
    shutil.copy2(RAIZ / "integration" / "ceibo-api.js", DIST / "ceibo-api.js")
    print(f"\nOK -> {DIST / 'index.html'}")
    print("Servir:  cd dist && python -m http.server 8080")


if __name__ == "__main__":
    main()
