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
  reloadDashboard = async () => {
    const d = await window.CeiboAPI.loadDashboard();
    this.setState({ dashboard: d });
  };
  async componentDidMount() {
    try {
      await window.CeiboAPI.init();
      await this.reloadEmpleados();
      await this.reloadNovedades();
      await this.reloadDashboard();
      this.setState({ tiposDoc: await window.CeiboAPI.listTiposDoc() });
      const e = this.state.empleados;
      if (e && e.length) { this.setState({ selEmp: e[0].id }); this.recargarDocs(e[0].id); }
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
    v.submitDoc = this.submitDoc;
    // El catálogo real reemplaza a los 4 tipos hardcodeados del canvas: RRHH puede dar de
    // alta tipos nuevos y el desplegable tiene que mostrarlos.
    if (this.state.tiposDoc) v.docTipos = this.state.tiposDoc;
    // Dashboard con datos reales: reemplaza las métricas mock del canvas.
    if (this.state.dashboard) {
      Object.assign(v, window.CeiboAPI.dashboardVals(this.state.dashboard, this.state.rot, v.metrics));
    }
    return v;
  }
  openAltaNov = () => {
    this.setState({ modal: 'altanov', editNovId: null, novFormTipo: 'Falta' });
    setTimeout(() => window.CeiboAPI.populateNovForm(), 60);
  };
  openEditNov = (id) => {
    this.setState({ modal: 'altanov', editNovId: id, editProrrogaIdx: null, novFormTipo: window.CeiboAPI.novFormTipoFor(id) });
    setTimeout(() => window.CeiboAPI.prefillNovForm(id), 60);
  };
  submitNov = async () => {
    try {
      // Si se está editando una prórroga (fila hija), el id real es el de la prórroga,
      // no el de la madre; se resuelve por (madre, índice) del estado del diseño.
      let editId = this.state.editNovId;
      if (this.state.editProrrogaIdx != null) {
        const n = this.novList().find(x => x.id === this.state.editNovId);
        const p = n && n.prorrogas && n.prorrogas[this.state.editProrrogaIdx];
        if (p && p.id != null) editId = p.id;
      }
      await window.CeiboAPI.submitNov(editId);
      this.setState({ modal: null, editNovId: null, editProrrogaIdx: null });
      await this.reloadNovedades();
    } catch (e) { console.error('[ceibo] novedad', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  // ===== acciones por fila de prórroga (el canvas las dejó en mock; acá van al backend) =====
  // El diseño identifica una prórroga por (id de la madre, índice); resolvemos el id real
  // del backend con prorrogas[idx].id (lo agrega CeiboAPI.listNovedades).
  _prorrogaId = (novId, idx) => {
    const n = this.novList().find(x => x.id === novId);
    const p = n && n.prorrogas && n.prorrogas[idx];
    return p ? p.id : null;
  };
  _transProrroga = async (novId, idx, accion) => {
    try {
      const id = this._prorrogaId(novId, idx);
      if (id == null) throw new Error('prórroga no encontrada');
      await window.CeiboAPI.transicionNov(id, accion);
      await this.reloadNovedades();
    } catch (e) { console.error('[ceibo] prórroga', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  aprobarProrroga = (novId, idx) => this._transProrroga(novId, idx, 'aprobar');
  rechazarProrroga = (novId, idx) => this._transProrroga(novId, idx, 'rechazar');
  anularProrroga = (novId, idx) => this._transProrroga(novId, idx, 'anular');
  openEditProrroga = (novId, idx) => {
    const id = this._prorrogaId(novId, idx);
    this.setState({ modal: 'altanov', editNovId: novId, editProrrogaIdx: idx,
      novFormTipo: id != null ? window.CeiboAPI.novFormTipoFor(id) : 'Falta' });
    if (id != null) setTimeout(() => window.CeiboAPI.prefillNovForm(id), 60);
  };
  _transNov = async (accion) => {
    try {
      await window.CeiboAPI.transicionNov(this.state.detNovId, accion);
      await this.reloadNovedades();   // el detalle se re-renderiza con el nuevo estado
    } catch (e) { console.error('[ceibo] transición', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  aprobarNov = () => this._transNov('aprobar');
  rechazarNov = () => this._transNov('rechazar');
  anularNov = () => this._transNov('anular');
  submitProrroga = async () => {
    try {
      await window.CeiboAPI.submitProrroga(this.state.detNovId);
      this.setState({ modal: null });
      await this.reloadNovedades();
    } catch (e) { console.error('[ceibo] prórroga', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  openAlta = () => {
    this.setState({ modal: 'alta', altaEditId: null });
    // Tras montar el modal: habilita empresa y fuerza elección consciente (opción vacía).
    setTimeout(() => window.CeiboAPI.prepareAlta(), 60);
  };
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
  confirmReingreso = async () => {
    try {
      const emp = (this.state.empleados || []).find(e => e.id === this.state.reingresoId);
      await window.CeiboAPI.reingreso(emp);   // lee la fecha del modal de reincorporación
      this.setState({ modal: null });
      await this.reloadEmpleados();
    } catch (e) { console.error('[ceibo] reingreso', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  selectEmp = (id) => {
    this.setState({ selEmp: id, view: 'ficha' });
    this.recargarDocs(id);
  };
  // ===== documentos de la ficha (el canvas los deja en mock; acá van al backend) =====
  recargarDocs = (id) => {
    const self = this;
    return window.CeiboAPI.loadDocs(id).then(function (docs) {
      self.setState(function (s) {
        return { empleados: (s.empleados || []).map(function (e) { return e.id === id ? Object.assign({}, e, { docs: docs }) : e; }) };
      });
    }).catch(function () {});
  };
  openDocNuevo = () => {
    this.setState({ modal: 'doc', docEditId: null, docArchivoNombre: '' });
    // Tras montar el modal: deja el select en el primer tipo libre (los ya cargados no
    // se pueden repetir: hay uno vigente por tipo y el POST fallaría con 400).
    setTimeout(() => window.CeiboAPI.prepareDoc(this.state.selEmp, null), 60);
  };
  openDocEdit = (id) => {
    this.setState({ modal: 'doc', docEditId: id, docArchivoNombre: '' });
    setTimeout(() => window.CeiboAPI.prepareDoc(this.state.selEmp, id), 60);
  };
  submitDoc = async () => {
    try {
      await window.CeiboAPI.submitDoc(this.state.selEmp, this.state.docEditId);
      this.setState({ modal: null, docEditId: null, docArchivoNombre: '' });
      await this.recargarDocs(this.state.selEmp);
    } catch (e) { console.error('[ceibo] documento', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  descargarDoc = async (id) => {
    // No es un <a href>: el endpoint pide el header Authorization y un link plano no lo
    // manda. Se baja con fetch autenticado y se entrega como blob.
    try { await window.CeiboAPI.descargarDoc(this.state.selEmp, id); }
    catch (e) { console.error('[ceibo] descarga', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  quitarDoc = async (id) => {
    try {
      await window.CeiboAPI.quitarDoc(this.state.selEmp, id);
      await this.recargarDocs(this.state.selEmp);
    } catch (e) { console.error('[ceibo] quitar documento', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  // ===== respaldos de la novedad (el canvas los deja en mock; acá van al backend) =====
  // `detNovId` es la novedad ABIERTA: si es una prórroga, sus respaldos son de ese eslabón.
  recargarAdjuntos = (novId) => {
    const self = this;
    return window.CeiboAPI.loadAdjuntos(novId)
      .then(function (as) { self.setState({ adjuntosDet: as }); })
      .catch(function () { self.setState({ adjuntosDet: [] }); });
  };
  openDetNov = (id) => {
    // adjuntosDet en null mientras carga: el canvas mostraría su ejemplo, así que se
    // arranca en [] para que se vea el estado vacío y no un respaldo que no existe.
    this.setState({ modal: 'detnov', detNovId: id, adjuntosDet: [] });
    this.recargarAdjuntos(id);
  };
  onAdjuntar = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';   // permite volver a elegir el mismo archivo si falló
    if (!file) return;
    try {
      await window.CeiboAPI.subirAdjunto(this.state.detNovId, file);
      await this.recargarAdjuntos(this.state.detNovId);
    } catch (err) { console.error('[ceibo] adjuntar', err); window.CeiboAPI.toast(err.message || String(err), 'error'); }
  };
  descargarAdjunto = async (id) => {
    try { await window.CeiboAPI.descargarAdjunto(this.state.detNovId, id); }
    catch (e) { console.error('[ceibo] descargar respaldo', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  quitarAdjunto = async (id) => {
    try {
      await window.CeiboAPI.quitarAdjunto(this.state.detNovId, id);
      await this.recargarAdjuntos(this.state.detNovId);
    } catch (e) { console.error('[ceibo] quitar respaldo', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
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
        "theme: 'dark', view: 'dashboard', selEmp: 1,\n    empleados: null, novedades: null, dashboard: null, apiErr: null, altaEditId: null, tiposDoc: null,",
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
        "  confirmReingreso = ()=> this.setState(s=>({ bajaSet: s.bajaSet.filter(x=>x!==s.reingresoId), modal:null }));\n}",
        BLOQUE_INTEGRACION,
        "clase: bloque de integración",
    ),
    # (El FIX del header malformado de "Registrar/Editar novedad" ya no hace falta:
    #  el export 2026-07-10 de Claude Design trae el header balanceado de fábrica.)
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
        "style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:430px;max-width:100%",
        "data-modal=\"reingreso\" style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:430px;max-width:100%",
        "modal reingreso: data-modal",
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
    (
        "style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:520px;max-width:100%",
        "data-modal=\"doc\" style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:520px;max-width:100%",
        "modal documento: data-modal",
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
    # (El campo "Fecha de egreso" del modal de baja y los botones de acción por fila en
    #  la cadena de novedad ahora vienen del canvas (export 2026-07-10). Ya no se inyectan;
    #  el cableado de esos botones al backend está en BLOQUE_INTEGRACION —overrides de
    #  aprobarProrroga/rechazarProrroga/anularProrroga/openEditProrroga—.)

    # (El filtro por empleado del grid de novedades —input + datalist, state novEmp,
    #  handler, condición en filteredNov y helper normEmp— ya no se inyecta: se subió al
    #  canvas el 2026-07-15 y el export del 2026-07-15 lo trae de fábrica. Sus 6 ediciones
    #  se borraron de acá al promoverlo, que era justo lo que su comentario indicaba hacer.)

    # --- template: botón Guardar documento → submitDoc (el canvas lo deja en closeModal) ---
    (
        '<button onClick="{{ closeModal }}" style="background:var(--accent);border:none;color:#04201C;font-weight:600;font-size:13px;border-radius:10px;padding:0 20px;height:40px;cursor:pointer;box-shadow:0 4px 14px rgba(45,212,191,.28)">Guardar documento</button>',
        '<button onClick="{{ submitDoc }}" style="background:var(--accent);border:none;color:#04201C;font-weight:600;font-size:13px;border-radius:10px;padding:0 20px;height:40px;cursor:pointer;box-shadow:0 4px 14px rgba(45,212,191,.28)">Guardar documento</button>',
        "botón Guardar documento → submitDoc",
    ),
    # --- dashboard: el ranking mide DÍAS (no cantidad de faltas); se aclara en el título ---
    (
        '<div style="font-weight:600;font-size:15px;color:var(--text)">Ranking de faltas</div>',
        '<div style="font-weight:600;font-size:15px;color:var(--text)">Ranking de faltas · días</div>',
        "dashboard: ranking título · días",
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

    # (La sección "Egreso" del alta ya no viene en el canvas (export 2026-07-10); no hay
    #  nada que remover acá.)

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
