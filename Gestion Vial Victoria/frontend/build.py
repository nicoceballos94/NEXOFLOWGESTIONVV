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
  reloadVencimientos = async () => {
    const v = await window.CeiboAPI.loadVencimientos();
    this.setState({ vencimientos: v });
  };
  reloadAlertasDia = async () => {
    const a = await window.CeiboAPI.loadAlertasDia();
    this.setState({ alertasDiaData: a });
  };
  reloadConfigVenc = async () => {
    const filas = await window.CeiboAPI.loadConfigVenc();
    this.setState({ cfgVenc: filas });
  };
  // El diseño pinta el semáforo (this.dot/semColor); 'info' no es parte de él —el cumpleaños
  // no es una alerta— así que usa el color de marca.
  _dotDe = (estado) => this.dot(estado === 'info' ? 'var(--accent)' : this.semColor(estado));
  _uiSem = () => ({
    dot: (c) => this.dot(c),
    badge: (k) => this.badge(k),
    semColor: (s) => this.semColor(s),
    semLabel: (s) => this.semLabel(s),
    dotDe: this._dotDe,
  });
  async componentDidMount() {
    try {
      await window.CeiboAPI.init();
      await this.reloadEmpleados();
      await this.reloadNovedades();
      await this.reloadDashboard();
      await this.reloadVencimientos();
      await this.reloadAlertasDia();
      await this.reloadConfigVenc();
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
    // Vencimientos reales: reemplazan los 4 grupos mock del canvas.
    if (this.state.vencimientos) {
      Object.assign(v, window.CeiboAPI.vencimientosVals(
        this.state.vencimientos, this._uiSem(), v.vencGroups));
    }
    // Alertas del día: reemplazan las 4 inventadas del canvas y descongelan la fecha.
    if (this.state.alertasDiaData) {
      Object.assign(v, window.CeiboAPI.alertasDiaVals(this.state.alertasDiaData, this._uiSem()));
    }
    // Destinatarios y canales: no hay backend donde guardarlos, así que se apagan en vez
    // de fingir que se configuran (ver CeiboAPI.notifVals).
    Object.assign(v, window.CeiboAPI.notifVals(v));
    // Parametría real: las filas salen del catálogo, así que un tipo nuevo aparece solo.
    if (this.state.cfgVenc) {
      v.cfgRows = this.state.cfgVenc.map((f) => ({
        label: f.label, hint: f.hint, val: f.dias,
        inc: () => this.cfgVencChange(f.clave, 5),
        dec: () => this.cfgVencChange(f.clave, -5),
      }));
    }
    return v;
  }
  // ===== parametría de alertas =====
  _cfgTimers = {};
  cfgVencChange = (clave, delta) => {
    // Optimista: el +/- tiene que responder en el acto. Si el guardado falla, se recarga
    // del server y el número vuelve solo — mejor que bloquear el botón esperando la red.
    this.setState((s) => ({
      cfgVenc: s.cfgVenc.map((f) => f.clave === clave
        ? { ...f, dias: Math.max(0, Math.min(180, f.dias + delta)) } : f),
    }));
    // Debounce: quien toca `+` cinco veces manda UN PATCH con el valor final y no cinco
    // que pueden llegar desordenados y dejar guardado un número intermedio.
    clearTimeout(this._cfgTimers[clave]);
    this._cfgTimers[clave] = setTimeout(() => this._guardarCfgVenc(clave), 500);
  };
  _guardarCfgVenc = async (clave) => {
    const fila = (this.state.cfgVenc || []).find((f) => f.clave === clave);
    if (!fila) return;
    try {
      await window.CeiboAPI.guardarDiasAviso(clave, fila.dias);
      // Lo que se acaba de configurar cambia el semáforo: sin esto, Alertas seguiría
      // mostrando el umbral viejo hasta la próxima recarga.
      this.reloadVencimientos();
      this.reloadAlertasDia();
    } catch (e) {
      console.error('[ceibo] config vencimientos', e);
      window.CeiboAPI.toast(e.message || String(e), 'error');
      await this.reloadConfigVenc();   // el server manda: se descarta lo optimista
    }
  };
  goCfg = () => { this.setView('config'); this.reloadConfigVenc(); };
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
    // `exento` es el toggle "Exento de marcación": estado del diseño, no un input del form.
    // Se arranca apagado, o el alta heredaría el valor de la última ficha que se abrió.
    this.setState({ modal: 'alta', altaEditId: null, exento: false });
    // Tras montar el modal: habilita empresa y fuerza elección consciente (opción vacía).
    setTimeout(() => window.CeiboAPI.prepareAlta(), 60);
  };
  openEdit = (id) => {
    const emp = (this.state.empleados || []).find(e => e.id === id);
    // Sembrar el toggle con el valor real: sin esto la ficha abría siempre en "no exento"
    // y guardar apagaba la exención de alguien que sí la tenía.
    this.setState({ modal: 'alta', altaEditId: id, exento: !!(emp && emp.exento_marcacion) });
    setTimeout(() => window.CeiboAPI.prefillAlta(emp), 60);
  };
  submitAlta = async () => {
    try {
      await window.CeiboAPI.submitAlta(this.state.altaEditId, this.state.exento);
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
  // Entrar a la pantalla recarga. Un documento cargado en una ficha, o un alta/baja, cambia
  // lo que vence; sin esto se vería el estado del momento en que se abrió la app. Es el
  // único punto de recarga a propósito: los vencimientos no se editan desde esta pantalla.
  goAle = () => { this.setView('alertas'); this.reloadVencimientos(); };
  goDash = () => { this.setView('dashboard'); this.reloadAlertasDia(); };
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
        "theme: 'dark', view: 'dashboard', selEmp: 1,\n    empleados: null, novedades: null, dashboard: null, apiErr: null, altaEditId: null, tiposDoc: null, vencimientos: null, alertasDiaData: null, cfgVenc: null,",
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
    # (La fecha de "Alertas del día" estaba congelada en el markup —"Viernes 4 de julio,
    #  2026"— y se cableó a `{{ hoyLabel }}`. No se inyecta: el cambio se subió al canvas el
    #  2026-07-15 y el diseño ya lo trae. El canvas calcula su propia fecha para verse solo;
    #  el valor real lo pisa CeiboAPI.alertasDiaVals.)

    # --- reportes: el módulo es mock y se señaliza como tal ---
    # Las series de Reportes (dotación, ausentismo por tipo, motivos de egreso) están
    # inventadas en el canvas y no hay endpoints que las alimenten. Sin marca, Reportes
    # informaba 134 activos mientras el Panel —que sí sale del backend— mostraba 12, y nada
    # indicaba cuál creer. Se avisa arriba de todo y se saca el número grande de la portada.
    (
        '<sc-if value="{{ isRep }}" hint-placeholder-val="{{ false }}">',
        '<sc-if value="{{ isRep }}" hint-placeholder-val="{{ false }}">\n'
        '      <div style="display:flex;align-items:flex-start;gap:11px;background:var(--surface);'
        'border:1px solid var(--warn);border-radius:12px;padding:13px 16px;margin-bottom:16px">'
        '<div style="width:8px;height:8px;border-radius:50%;background:var(--warn);flex:none;margin-top:6px"></div>'
        '<div><div style="font-size:13.5px;font-weight:600;color:var(--text)">Datos de demostración</div>'
        '<div style="font-size:12px;color:var(--text3);line-height:1.5">Este módulo todavía no está '
        'conectado al backend: las cifras son de ejemplo y no describen la dotación real. '
        'Los números reales están en el Panel general.</div></div></div>',
        "reportes: banner de datos de demostración",
    ),
    (
        '<div style="font-family:\'Space Grotesk\',sans-serif;font-weight:600;font-size:22px;color:var(--text)">134 <span style="font-size:12px;color:var(--ok);font-weight:600">▲ 13,6%</span></div>',
        '<div style="font-family:\'Space Grotesk\',sans-serif;font-weight:600;font-size:13px;color:var(--text3)">ejemplo</div>',
        "reportes: quitar el total mock de dotación",
    ),
    # --- configuración: el bloque de destinatarios no persiste; se dice en el subtítulo ---
    (
        '<div style="font-size:12.5px;color:var(--text3);margin-bottom:18px">A quién y por dónde se envían los avisos de vencimiento.</div>',
        '<div style="font-size:12.5px;color:var(--text3);margin-bottom:18px">{{ notifSubtitle }}</div>',
        "config: subtítulo de destinatarios → notifSubtitle",
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
