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
import hashlib
import re
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
  reloadReportes = async () => {
    const r = await window.CeiboAPI.loadReportes();
    this.setState({ reportes: r });
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
  // Toda la carga inicial, ya con sesión abierta. Antes vivía en componentDidMount porque
  // el token se pedía solo con credenciales fijas; ahora arranca cuando hay una persona
  // autenticada — al entrar por el login o al restaurar la sesión tras un F5.
  async cargarTodo() {
    try {
      this.setState({ cargaInicial: 'cargando' });
      await window.CeiboAPI.init();
      await this.reloadEmpleados();
      await this.reloadNovedades();
      await this.reloadDashboard();
      await this.reloadReportes();
      await this.reloadVencimientos();
      await this.reloadAlertasDia();
      await this.reloadConfigVenc();
      this.setState({ tiposDoc: await window.CeiboAPI.listTiposDoc() });
      const e = this.state.empleados;
      if (e && e.length) { this.setState({ selEmp: e[0].id }); this.recargarDocs(e[0].id); }
      this.setState({ cargaInicial: 'lista' });
    } catch (err) {
      console.error('[ceibo] init', err);
      // 'error' —y no 'lista'— a propósito: si la carga falló, los módulos siguen tapados.
      // Destaparlos mostraría los mocks del canvas como si fueran la dotación real.
      this.setState({ apiErr: String(err), cargaInicial: 'error' });
    }
  }
  // Login real contra /auth/token/ (reemplaza la maqueta del canvas, que solo validaba
  // que los campos no estuvieran vacíos).
  doLogin = async (e) => {
    if (e && e.preventDefault) e.preventDefault();
    const S = this.state;
    if (!String(S.loginUsuario || '').trim() || !S.loginClave) {
      this.setState({ loginError: 'Completá usuario y contraseña.' });
      return;
    }
    if (S.loginOcupado) return;   // doble Enter no dispara dos logins (y dos golpes al throttle)
    this.setState({ loginOcupado: true, loginError: '' });
    try {
      await window.CeiboAPI.login(S.loginUsuario.trim(), S.loginClave);
      // La clave no queda en el estado ni un momento más de lo necesario.
      this.setState({ sesion: true, loginOcupado: false, loginClave: '', loginError: '' });
      window.CeiboAPI.a11ySesion(true);   // se abre la app: el fondo deja de estar inerte (ALTO-03)
      await this.cargarTodo();
    } catch (err) {
      this.setState({ loginOcupado: false, loginClave: '', loginError: String(err.message || err) });
    }
  };
  doLogout = () => {
    window.CeiboAPI.logout();
    window.CeiboAPI.a11ySesion(false);   // vuelve el login: el fondo se apaga del árbol accesible
    // Los datos de la sesión anterior se van con ella: si no, el siguiente en entrar ve
    // por un instante la dotación del anterior antes de que termine su propia carga.
    this.setState({
      sesion: false, loginUsuario: '', loginClave: '', loginError: '', loginOcupado: false,
      view: 'dashboard', cargaInicial: 'cargando', apiErr: null,
      empleados: null, novedades: null, dashboard: null, reportes: null, vencimientos: null,
      alertasDiaData: null, cfgVenc: null, tiposDoc: null,
      // Los blobs de foto los revocó CeiboAPI.logout(); hay que soltar también sus URLs acá,
      // o ensureFoto ve la entrada vieja y no rebaja la foto → <img> a un blob muerto (rota).
      empresasCfgData: null, sectoresCfgData: null, fotoUrlByEmp: {},
    });
  };
  async componentDidMount() {
    // Si la sesión murió sola (refresh vencido o revocado), volver al login en vez de
    // dejar la app mostrando datos que ya no se pueden actualizar.
    window.CeiboAPI.onSesionVencida(() => {
      if (!this.state.sesion) return;
      this.doLogout();
      this.setState({ loginError: 'Tu sesión venció. Ingresá de nuevo.' });
    });
    // Arranca sin sesión (login a la vista): el fondo va inerte ya, antes de resolver la
    // restauración, para que no quede ni un frame con el shell navegable detrás del login.
    window.CeiboAPI.a11ySesion(false);
    let hay = false;
    try {
      hay = await window.CeiboAPI.restaurarSesion();
    } catch (err) {
      console.warn('[ceibo] no se pudo restaurar la sesión', err);
    }
    // Sin sesión, el fondo va inerte: el login lo tapa visualmente pero sin esto seguía en el
    // árbol accesible (sidebar, header, todas las acciones y los datos mock). Con sesión, activo.
    window.CeiboAPI.a11ySesion(hay);
    if (!hay) return;             // sin sesión: queda la pantalla de login
    this.setState({ sesion: true });
    await this.cargarTodo();
  }
  renderVals() {
    const v = this.renderValsBase();
    // Dato utilizable: descarta null (sin cargar / fallo de red) y el marcador SIN_PERMISO (403).
    // Sin esto, un módulo que el rol no puede ver se quedaría con los datos de ejemplo del canvas.
    const _real = (x) => !!x && !window.CeiboAPI.esSinPermiso(x);
    // El canvas trae datos de ejemplo hardcodeados (134 activos, rankings, alertas) para
    // poder diseñarse solo. Hasta que termina la primera carga, `base()`/`novBase()`/
    // `metrics` devuelven ESOS valores, así que la app abría mostrando cifras inventadas
    // y recién ~1s después las reemplazaba por las reales. Mientras carga no se muestra
    // ningún módulo: se muestra el panel de carga, y si la API falló, el error.
    const carga = this.state.cargaInicial;
    v.cargandoInit = carga === 'cargando';
    v.errorInit = carga === 'error';
    // Copy por defecto del panel de error (el markup del canvas dejó de tener texto fijo: build.py
    // lo ató a estas vars). El bloque de "sin permiso", más abajo, las pisa para un 403.
    v.errorTitle = 'No se pudieron cargar los datos';
    v.errorText = 'No se muestra nada en vez de mostrar información de ejemplo. Reintentá recargando la página.';
    // Sesión: el canvas define doLogin/doLogout como maqueta (entra con cualquier campo no
    // vacío). Acá se pisan por los reales, y el pie del sidebar deja de decir "Luciana
    // Sosa · Referente RRHH" para decir quién entró de verdad.
    v.doLogin = this.doLogin;
    v.doLogout = this.doLogout;
    if (this.state.sesion) {
      const p = window.CeiboAPI.perfilVals();
      v.userNombre = p.nombre;
      v.userRol = p.rol;
      v.userIniciales = (p.nombre || '').trim().split(/\s+/).slice(0, 2)
        .map(x => x.charAt(0).toUpperCase()).join('') || '·';
      // Capacidades del rol (A5): el canvas expone los hooks puedeX con default true para
      // poder diseñarse sin sesión; acá se pisan con lo que el backend habilita de verdad
      // (CeiboAPI.puede, restrictivo por defecto). Esto ESCONDE botones; la seguridad real
      // sigue siendo el 403 del backend. Solo con sesión: es cuando perfilVals ya garantiza
      // que CeiboAPI está cargado (mismo patrón que userRol, arriba).
      v.puedeEscribirEmpleado = window.CeiboAPI.puede('empleados_escribir');
      v.puedeCargarNovedad = window.CeiboAPI.puede('novedades_cargar');
      v.puedeDecidirNovedad = window.CeiboAPI.puede('novedades_decidir');
      v.puedeConfig = window.CeiboAPI.puede('config_escribir');
      // El detalle de novedad ya trae sc-if por ESTADO (canAprobar = ¿está en un estado
      // aprobable?). Eso responde "¿se puede?" por la máquina de estados, no por el rol.
      // Acá se le suma el rol: un botón se muestra solo si el estado lo permite Y el rol
      // puede ejecutarlo. Decidir (aprobar/rechazar/anular) es RRHH+ (R11); editar,
      // prorrogar y adjuntar son operativos (Supervisor+).
      if (v.detNov) {
        var dn = v.detNov;
        dn.puedeAdjuntar = v.puedeCargarNovedad;   // era fijo en true en el canvas
        dn.canEdit = dn.canEdit && v.puedeCargarNovedad;
        dn.puedeProrrogar = dn.puedeProrrogar && v.puedeCargarNovedad;
        dn.canAprobar = dn.canAprobar && v.puedeDecidirNovedad;
        dn.canRechazar = dn.canRechazar && v.puedeDecidirNovedad;
        dn.canAnular = dn.canAnular && v.puedeDecidirNovedad;
        // Cada eslabón de la cadena (madre + prórrogas) repite las mismas acciones por fila.
        if (Array.isArray(dn.timeline)) dn.timeline.forEach(function (t) {
          t.canEdit = t.canEdit && v.puedeCargarNovedad;
          t.canAprobar = t.canAprobar && v.puedeDecidirNovedad;
          t.canRechazar = t.canRechazar && v.puedeDecidirNovedad;
          t.canAnular = t.canAnular && v.puedeDecidirNovedad;
        });
      }
    }
    v.apiErrMsg = this.state.apiErr || '';
    if (carga !== 'lista') {
      v.isDash = false; v.isEmp = false; v.isFicha = false; v.isNov = false;
      v.isAle = false; v.isRep = false; v.isCfg = false;
    }
    v.submitAlta = this.submitAlta;
    v.altaTitle = this.state.altaEditId ? 'Editar empleado' : 'Alta de empleado';
    if (v.ficha) {
      v.ficha.openEdit = () => this.openEdit(this.state.selEmp);
      // Foto de perfil: el objectURL real (blob autenticado, no la URL de la API) vive en el
      // estado; el canvas deja la ficha con avatar de iniciales. Los controles reusan la
      // capacidad de escritura de empleados (el backend acota foto a RRHH/Admin igual que el ABM).
      var _fUrl = (this.state.fotoUrlByEmp || {})[this.state.selEmp] || '';
      v.ficha.fotoUrl = _fUrl;
      v.ficha.tieneFotoView = !!_fUrl;
      v.ficha.sinFoto = !_fUrl;
      v.ficha.puedeFoto = !!v.puedeEscribirEmpleado;
      v.ficha.mostrarQuitarFoto = !!_fUrl && !!v.puedeEscribirEmpleado;
      v.ficha.onFotoInput = this.onFotoInput;
      v.ficha.quitarFoto = this.quitarFotoFicha;
    }
    // El canvas define setRotM/setRotA en la clase pero nunca los expone en renderVals, así
    // que el template los ata a undefined y los botones Mensual/Anual no hacían NADA: ni
    // cambiaban de estilo ni recalculaban la rotación (el backend sí manda ambos períodos).
    v.setRotM = this.setRotM;
    v.setRotA = this.setRotA;
    v.submitNov = this.submitNov;
    v.submitProrroga = this.submitProrroga;
    v.submitDoc = this.submitDoc;
    // El catálogo real reemplaza a los 4 tipos hardcodeados del canvas: RRHH puede dar de
    // alta tipos nuevos y el desplegable tiene que mostrarlos.
    if (this.state.tiposDoc) v.docTipos = this.state.tiposDoc;
    // Dashboard con datos reales: reemplaza las métricas mock del canvas.
    if (_real(this.state.dashboard)) {
      Object.assign(v, window.CeiboAPI.dashboardVals(this.state.dashboard, this.state.rot, v.metrics));
    }
    // Reportes con datos reales: dotación en el tiempo, ausentismo por tipo y motivos de
    // egreso. Reemplazan las series inventadas del canvas (y con ellas el banner de demo).
    if (_real(this.state.reportes)) {
      Object.assign(v, window.CeiboAPI.reportesVals(this.state.reportes));
    }
    // Vencimientos reales: reemplazan los 4 grupos mock del canvas.
    if (_real(this.state.vencimientos)) {
      Object.assign(v, window.CeiboAPI.vencimientosVals(
        this.state.vencimientos, this._uiSem(), v.vencGroups));
    }
    // Alertas del día: reemplazan las 4 inventadas del canvas y descongelan la fecha.
    if (_real(this.state.alertasDiaData)) {
      Object.assign(v, window.CeiboAPI.alertasDiaVals(this.state.alertasDiaData, this._uiSem()));
    }
    // Destinatarios y canales: no hay backend donde guardarlos, así que se apagan en vez
    // de fingir que se configuran (ver CeiboAPI.notifVals).
    // El guard es a propósito: renderVals corre en CADA render y fuera de todo try/catch,
    // así que si CeiboAPI no trae este método la excepción se lleva puesta la app entera
    // (pantalla en blanco, no un módulo roto). Los nombres hasheados de build.py hacen
    // imposible el desajuste que lo provocó; esto asegura que el modo de falla, si algún
    // día vuelve, sea perder un bloque de Configuración y no toda la pantalla.
    // Se chequea también que exista CeiboAPI: si el archivo no cargó (404), no es que falte
    // el método sino el objeto entero, y `window.CeiboAPI.notifVals` ya tira al leerlo.
    if (window.CeiboAPI && typeof window.CeiboAPI.notifVals === 'function') {
      Object.assign(v, window.CeiboAPI.notifVals(v));
    } else {
      console.error('[ceibo] CeiboAPI.notifVals no está disponible; ¿ceibo-api.js desactualizado?');
    }
    // Parametría real: las filas salen del catálogo, así que un tipo nuevo aparece solo.
    if (_real(this.state.cfgVenc)) {
      // Los aria van acá también: este override reemplaza a cfgRows del canvas, así que
      // sin esto todos los botones se seguirían anunciando como "+" y "−" a secas.
      v.cfgRows = this.state.cfgVenc.map((f) => ({
        label: f.label, hint: f.hint, val: f.dias,
        incAria: `Aumentar días de aviso para ${f.label}`,
        decAria: `Reducir días de aviso para ${f.label}`,
        inc: () => this.cfgVencChange(f.clave, 5),
        dec: () => this.cfgVencChange(f.clave, -5),
      }));
    }
    // MEDIO-03: los encabezados de los acordeones de Configuración son <div onClick>. El markup
    // les agrega role=button/tabindex/aria-expanded (build.py); el handler de teclado va acá,
    // colgado de cada sección, para que Enter/Espacio los abran igual que el click.
    if (v.cfgUI) {
      Object.keys(v.cfgUI).forEach((k) => {
        const sec = v.cfgUI[k];
        if (sec && typeof sec.toggle === 'function') {
          sec.toggleKey = (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sec.toggle(); }
          };
        }
      });
    }
    // MENOR-03: el badge del menú cuenta TODAS las novedades (no las pendientes). Sin rótulo, un
    // lector de pantalla lo puede leer como "pendientes". Se aclara qué mide, sin cambiar el
    // número visible (mostrar solo pendientes sería un cambio de producto, no de accesibilidad).
    v.novBadgeAria = (v.novCount != null ? v.novCount : '') + ' novedades en total';
    // ALTO-01: la vista actual sin permiso (403) o sin datos NO debe quedarse con los mocks del
    // canvas. Se apaga el módulo y se reusa el panel de error con el aviso que corresponda.
    const _modVista = { dashboard: this.state.dashboard, reportes: this.state.reportes,
      alertas: this.state.vencimientos, config: this.state.cfgVenc };
    if (carga === 'lista' && (this.state.view in _modVista)) {
      const _d = _modVista[this.state.view];
      const _sinPermiso = window.CeiboAPI.esSinPermiso(_d);
      if (_sinPermiso || _d === null) {
        v.isDash = false; v.isEmp = false; v.isFicha = false; v.isNov = false;
        v.isAle = false; v.isRep = false; v.isCfg = false;
        v.errorInit = true;
        if (_sinPermiso) {
          v.errorTitle = 'No tenés permisos para ver esta sección';
          v.errorText = 'Tu rol no tiene acceso a este módulo. Si creés que es un error, avisá a Administración.';
          v.apiErrMsg = '';   // un 403 no es un error técnico que haya que mostrar
        } else {
          v.errorTitle = 'No se pudo cargar esta sección';
          v.errorText = 'No se muestra nada en vez de mostrar información de ejemplo. Reintentá recargando la página.';
        }
      }
    }
    return v;
  }
  // ===== accesibilidad de los modales (BUG-12) =====
  // El rol y el aria-modal los declara el canvas; el foco es comportamiento y va acá.
  // Un solo punto de entrada por modal, llamado después de que el DOM ya montó.
  _a11y = (sel) => setTimeout(() => window.CeiboAPI.a11yModal(sel), 80);
  closeModal = () => {
    this.setState({ modal: null, editNovId: null, editProrrogaIdx: null, docEditId: null, docArchivoNombre: '' });
    window.CeiboAPI.a11yCerrar();   // el foco vuelve al botón que abrió el diálogo
  };
  // ===== listado de empleados: búsqueda, contador y alcance del buscador =====
  // Normaliza para comparar: sin mayúsculas, sin tildes y sin puntos. "María" y "maria"
  // son la misma persona, y quien busca no sabe cómo se cargó el acento.
  normBusq = (s) => String(s || '').trim().toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\./g, '');
  // El contador tiene que decir la verdad sobre lo que se está mirando: si el filtro es
  // "Inactivos", el denominador son los inactivos y la palabra es "inactivos".
  empCountLabel = (mostrados, todos, filtro) => {
    const palabra = filtro === 'activo' ? 'activos'
      : filtro === 'inactivo' ? 'inactivos' : 'empleados';
    const total = filtro === 'todos' ? todos.length
      : todos.filter((e) => e.estado === filtro).length;
    const empresas = new Set(todos.map((e) => e.empresa).filter((x) => x && x !== '—')).size;
    return `Mostrando ${mostrados.length} de ${total} ${palabra} · ` +
      `${empresas} ${empresas === 1 ? 'empresa' : 'empresas'}`;
  };
  // El buscador solo filtra Empleados, pero el término quedaba escrito en el encabezado al
  // navegar a Novedades o Alertas, como si esas pantallas estuvieran filtradas por él. Se
  // limpia al salir de Empleados (y de la ficha, que es su detalle).
  setView = (v) => {
    const dejaEmpleados = v !== 'empleados' && v !== 'ficha';
    this.setState(dejaEmpleados ? { view: v, empSearch: '' } : { view: v });
    // Los módulos comparten un solo <main> con scroll propio, así que la posición de la
    // pantalla anterior sobrevivía al cambio de vista: se entraba a Empleados con 137 px
    // de scroll y el título y los filtros quedaban tapados por el encabezado. Se vuelve
    // arriba después del render (antes, el DOM todavía tiene el alto de la vista vieja).
    window.CeiboAPI.scrollMainTop();
  };
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
  goCfg = () => { this.setView('config'); this.reloadConfigVenc(); this.reloadEmpresasCfg(); this.reloadSectoresCfg(); };
  openAltaNov = () => {
    // praxis: false a propósito (ALTO-02). El estado del canvas arranca con praxis:true, así que
    // un alta nueva abría con "Requiere praxis" activado y los campos médicos/ART visibles aunque
    // el tipo por defecto sea "Falta" —y el adaptador terminaba mandando requiere_praxis=true—.
    this.setState({ modal: 'altanov', editNovId: null, novFormTipo: 'Falta', praxis: false });
    setTimeout(() => window.CeiboAPI.populateNovForm(), 60);
    this._a11y('[data-modal="altanov"]');
  };
  openEditNov = (id) => {
    // En edición el toggle refleja el valor real de la novedad (no el que quedó de la última vez
    // que se abrió el modal): editar un accidente sigue mostrando sus campos de praxis.
    const n = this.novList().find((x) => x.id === id);
    this.setState({ modal: 'altanov', editNovId: id, editProrrogaIdx: null,
      novFormTipo: window.CeiboAPI.novFormTipoFor(id), praxis: !!(n && n.praxis) });
    setTimeout(() => window.CeiboAPI.prefillNovForm(id), 60);
    this._a11y('[data-modal="altanov"]');
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
    this._a11y('[data-modal="alta"]');
  };
  openEdit = (id) => {
    const emp = (this.state.empleados || []).find(e => e.id === id);
    // Sembrar el toggle con el valor real: sin esto la ficha abría siempre en "no exento"
    // y guardar apagaba la exención de alguien que sí la tenía.
    this.setState({ modal: 'alta', altaEditId: id, exento: !!(emp && emp.exento_marcacion) });
    setTimeout(() => window.CeiboAPI.prefillAlta(emp), 60);
    this._a11y('[data-modal="alta"]');
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
    this.ensureFoto(id);
  };
  // ===== foto de perfil de la ficha (el canvas la deja en avatar de iniciales) =====
  // La foto se descarga como blob con Authorization (media/ no es público), así que no puede
  // ir directo en <img src> a la API: se cachea un objectURL en el estado por empleado.
  // fotoUrlByEmp[id] === undefined => todavía no se intentó; '' => se intentó y no hay.
  ensureFoto = (id) => {
    if (id == null) return;
    if ((this.state.fotoUrlByEmp || {})[id] !== undefined) return;   // ya cargada o ya intentada
    const emp = (this.state.empleados || []).find((e) => e.id === id);
    if (!emp || !emp.tieneFoto) return;                              // sin foto: se queda con iniciales
    window.CeiboAPI.fotoObjectURL(id).then((url) => {
      this.setState((s) => ({ fotoUrlByEmp: Object.assign({}, s.fotoUrlByEmp, { [id]: url || '' }) }));
    }).catch((e) => console.warn('[ceibo] foto', e));
  };
  onFotoInput = async (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';   // permite volver a elegir el mismo archivo tras un error
    if (!file) return;
    const id = this.state.selEmp;
    try {
      await window.CeiboAPI.subirFoto(id, file);
      const url = await window.CeiboAPI.fotoObjectURL(id);
      this.setState((s) => ({ fotoUrlByEmp: Object.assign({}, s.fotoUrlByEmp, { [id]: url || '' }) }));
      await this.reloadEmpleados();   // refresca tieneFoto en la lista
    } catch (err) { console.error('[ceibo] subir foto', err); window.CeiboAPI.toast(err.message || String(err), 'error'); }
  };
  quitarFotoFicha = async () => {
    const id = this.state.selEmp;
    try {
      await window.CeiboAPI.quitarFoto(id);
      this.setState((s) => { const m = Object.assign({}, s.fotoUrlByEmp); delete m[id]; return { fotoUrlByEmp: m }; });
      await this.reloadEmpleados();
    } catch (err) { console.error('[ceibo] quitar foto', err); window.CeiboAPI.toast(err.message || String(err), 'error'); }
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
    this._a11y('[data-modal="doc"]');
  };
  openDocEdit = (id) => {
    this.setState({ modal: 'doc', docEditId: id, docArchivoNombre: '' });
    setTimeout(() => window.CeiboAPI.prepareDoc(this.state.selEmp, id), 60);
    this._a11y('[data-modal="doc"]');
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
    // Este modal no lleva data-modal (no se leen inputs de él), así que se lo toma por su
    // rol: solo hay un diálogo abierto por vez.
    this._a11y('[role="dialog"]');
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
  // ===== ABM de empresas y sectores (el canvas los deja en mock; acá van al backend) =====
  // El catálogo del ABM lista TODOS (activos e inactivos) para poder reactivar; el dropdown
  // del alta usa otra lista (solo activos), que mantiene CeiboAPI aparte.
  reloadEmpresasCfg = async () => {
    try { this.setState({ empresasCfgData: await window.CeiboAPI.listEmpresas() }); }
    catch (e) { console.warn('[ceibo] empresas cfg', e); }
  };
  reloadSectoresCfg = async () => {
    try { this.setState({ sectoresCfgData: await window.CeiboAPI.listSectores() }); }
    catch (e) { console.warn('[ceibo] sectores cfg', e); }
  };
  _readOrg = (campo) => {
    const el = document.querySelector('[data-modal="' + this._orgModal() + '"] [data-org="' + campo + '"]');
    return el ? el.value.trim() : '';
  };
  _orgModal = () => (this.state.modal === 'sector' ? 'sector' : 'empresa');
  _prefillOrg = (valores) => setTimeout(() => {
    const m = document.querySelector('[data-modal="' + this._orgModal() + '"]');
    if (!m) return;
    m.querySelectorAll('[data-org]').forEach((el) => { el.value = valores[el.getAttribute('data-org')] || ''; });
  }, 60);
  openEmpresaNueva = () => { this.setState({ modal: 'empresa', orgEditId: null }); this._prefillOrg({}); this._a11y('[data-modal="empresa"]'); };
  openEmpresaEdit = (id) => {
    const e = (this.state.empresasCfgData || []).find((x) => x.id === id) || {};
    this.setState({ modal: 'empresa', orgEditId: id });
    this._prefillOrg({ nombre: e.nombre, razon_social: e.razon_social, cuit: e.cuit });
    this._a11y('[data-modal="empresa"]');
  };
  submitEmpresa = async () => {
    try {
      const datos = { nombre: this._readOrg('nombre'), razon_social: this._readOrg('razon_social'), cuit: this._readOrg('cuit') };
      if (this.state.orgEditId != null) await window.CeiboAPI.editarEmpresa(this.state.orgEditId, datos);
      else await window.CeiboAPI.crearEmpresa(datos);
      this.setState({ modal: null, orgEditId: null });
      await this.reloadEmpresasCfg();
    } catch (e) { console.error('[ceibo] empresa', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  toggleEmpresaCfg = async (id) => {
    try {
      const e = (this.state.empresasCfgData || []).find((x) => x.id === id);
      if (!e) return;
      await window.CeiboAPI.toggleEmpresaActiva(id, !e.activa);
      await this.reloadEmpresasCfg();
    } catch (err) { console.error('[ceibo] baja empresa', err); window.CeiboAPI.toast(err.message || String(err), 'error'); }
  };
  openSectorNuevo = () => { this.setState({ modal: 'sector', orgEditId: null }); this._prefillOrg({}); this._a11y('[data-modal="sector"]'); };
  openSectorEdit = (id) => {
    const s = (this.state.sectoresCfgData || []).find((x) => x.id === id) || {};
    this.setState({ modal: 'sector', orgEditId: id });
    this._prefillOrg({ nombre: s.nombre });
    this._a11y('[data-modal="sector"]');
  };
  submitSector = async () => {
    try {
      const datos = { nombre: this._readOrg('nombre') };
      if (this.state.orgEditId != null) await window.CeiboAPI.editarSector(this.state.orgEditId, datos);
      else await window.CeiboAPI.crearSector(datos);
      this.setState({ modal: null, orgEditId: null });
      await this.reloadSectoresCfg();
    } catch (e) { console.error('[ceibo] sector', e); window.CeiboAPI.toast(e.message || String(e), 'error'); }
  };
  toggleSectorCfg = async (id) => {
    try {
      const s = (this.state.sectoresCfgData || []).find((x) => x.id === id);
      if (!s) return;
      await window.CeiboAPI.toggleSectorActivo(id, !s.activo);
      await this.reloadSectoresCfg();
    } catch (err) { console.error('[ceibo] baja sector', err); window.CeiboAPI.toast(err.message || String(err), 'error'); }
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
    # --- head: index.html nunca se cachea ---
    # Los assets van con hash y se pueden cachear para siempre; el index es el que dice
    # cuáles son, así que servir uno viejo deja al usuario en la versión anterior después
    # de desplegar. Lo correcto es el header Cache-Control del servidor —esto es el
    # refuerzo que viaja con el archivo y funciona con `python -m http.server`, que no
    # manda headers de caché.
    (
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta http-equiv="Cache-Control" content="no-cache, must-revalidate">',
        "head: no cachear index.html",
    ),
    # --- state: campos nuevos ---
    (
        "theme: 'dark', view: 'dashboard', selEmp: 1,",
        "theme: 'dark', view: 'dashboard', selEmp: 1,\n    empleados: null, novedades: null, dashboard: null, reportes: null, apiErr: null, altaEditId: null, tiposDoc: null, vencimientos: null, alertasDiaData: null, cfgVenc: null,\n    empresasCfgData: null, sectoresCfgData: null, fotoUrlByEmp: {},\n    cargaInicial: 'cargando',",
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
    # --- empresasCfgBase()/sectoresCfgBase(): datos reales del ABM si están cargados ---
    (
        "  empresasCfgBase(){\n    return [",
        "  empresasCfgBase(){\n    if (this.state.empresasCfgData) return this.state.empresasCfgData;\n    return [",
        "empresasCfgBase(): guard de datos reales",
    ),
    (
        "  sectoresCfgBase(){\n    return [",
        "  sectoresCfgBase(){\n    if (this.state.sectoresCfgData) return this.state.sectoresCfgData;\n    return [",
        "sectoresCfgBase(): guard de datos reales",
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
    # --- panel de error: copy dinámico (carga fallida vs. sin permiso, ALTO-01) ---
    # El canvas trae el texto fijo "No se pudieron cargar los datos". Se ata a vars para que el
    # mismo panel sirva de aviso de "no tenés permisos" cuando el rol recibe un 403, en vez de
    # dejar la vista con los datos de ejemplo del canvas. La lógica está en renderVals.
    (
        '<div style="font-size:13.5px;font-weight:600;color:var(--text)">No se pudieron cargar los datos</div>',
        '<div style="font-size:13.5px;font-weight:600;color:var(--text)">{{ errorTitle }}</div>',
        "panel de error: título → errorTitle",
    ),
    (
        '<div style="font-size:12px;color:var(--text3);line-height:1.5">No se muestra nada en vez de mostrar información de ejemplo. Reintentá recargando la página.</div>',
        '<div style="font-size:12px;color:var(--text3);line-height:1.5">{{ errorText }}</div>',
        "panel de error: texto → errorText",
    ),
    # (El FIX del header malformado de "Registrar/Editar novedad" ya no hace falta:
    #  el export 2026-07-10 de Claude Design trae el header balanceado de fábrica.)
    # (El panel de "Cargando datos…" / error de carga y su @keyframes spin ya no se
    #  inyectan: se subieron al canvas el 2026-07-20 y el diseño los trae de fábrica.
    #  La LÓGICA que decide cuándo mostrarlos —cargaInicial y el apagado de los módulos—
    #  sigue en BLOQUE_INTEGRACION: es cableado, no diseño.)
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
    (
        "style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:480px;max-width:100%",
        "data-modal=\"empresa\" style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:480px;max-width:100%",
        "modal empresa: data-modal",
    ),
    (
        "style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:400px;max-width:100%",
        "data-modal=\"sector\" style=\"background:var(--bg2);border:1px solid var(--border2);border-radius:18px;width:400px;max-width:100%",
        "modal sector: data-modal",
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

    # (El layout móvil ya no se inyecta: se subió al canvas el 2026-07-20 y el export lo
    #  trae de fábrica. Eran nueve ediciones —las clases ceibo-emp-head/emp-row/cfg-row/
    #  nov-head/nov-row, sus media queries y el sr-only del menú lateral— y se borraron de
    #  acá al promoverlo, que es lo que indicaba su propio comentario. Ojo: esas clases son
    #  ahora ANCLAS DE DISEÑO. Si un rediseño las quita, el layout móvil de Empleados,
    #  Novedades y Configuración se rompe en silencio, sin que este script corte.)
    # --- empleados: buscar ignorando tildes (BUG-08) ---
    # `toLowerCase().indexOf()` no normaliza: buscar "maria" encontraba "Maria Agust Cardoso"
    # pero no "María Godoy" ni "María López", que es justo lo que se estaba buscando. El DNI
    # se compara sin puntos para que "12.345.678" y "12345678" sean el mismo número.
    (
        "    const q = S.empSearch.trim().toLowerCase();",
        "    const q = this.normBusq(S.empSearch);",
        "empleados: normalizar el término de búsqueda",
    ),
    (
        "      if(q && !(e.name.toLowerCase().indexOf(q)>=0 || e.dni.indexOf(q)>=0)) return false;",
        "      if(q && !(this.normBusq(e.name).indexOf(q)>=0 || String(e.dni||'').replace(/\\./g,'').indexOf(q)>=0)) return false;",
        "empleados: comparar sin tildes ni puntos",
    ),
    # --- empleados: el contador tiene que describir el filtro puesto (BUG-09) ---
    # Con "Inactivos" seleccionado decía "Mostrando 0 de 12 activos": ni la palabra ni el
    # denominador seguían al filtro. Y las empresas se cuentan, no se dan por dos.
    (
        "      empCountLbl:`Mostrando ${filteredEmployees.length} de ${totalActivos} activos · 2 empresas`,",
        "      empCountLbl:this.empCountLabel(filteredEmployees, emps, S.empEstado),",
        "empleados: contador según el filtro",
    ),
    # --- reportes: las tres métricas salen del backend (/reportes/metricas/) ---
    # Antes el módulo era mock: series inventadas en el canvas, un banner de "datos de
    # demostración" y el número grande fijo en 134 mientras el Panel mostraba la dotación
    # real. Ahora `reportesVals` alimenta las tres visualizaciones, así que el número, la
    # variación, el sparkline, las barras de ausentismo y la dona describen la dotación real.
    # El total y la variación de dotación (número grande de la portada).
    (
        '<div style="font-family:\'Space Grotesk\',sans-serif;font-weight:600;font-size:22px;color:var(--text)">134 <span style="font-size:12px;color:var(--ok);font-weight:600">▲ 13,6%</span></div>',
        '<div style="font-family:\'Space Grotesk\',sans-serif;font-weight:600;font-size:22px;color:var(--text)">{{ repDotTotal }} <span style="{{ repDotDeltaStyle }}">{{ repDotDelta }}</span></div>',
        "reportes: total y variación de dotación reales",
    ),
    # El área bajo la curva del sparkline de dotación.
    (
        '<path d="M20,170 L20,142 L67.3,135 L114.5,131.5 L161.8,121 L209.1,124.5 L256.4,114 L303.6,107 L350.9,110.5 L398.2,100 L445.5,96.5 L492.7,89.5 L540,86 L540,170 Z" fill="url(#dotG)"/>',
        '<path d="{{ repDotArea }}" fill="url(#dotG)"/>',
        "reportes: área del sparkline de dotación",
    ),
    # La línea del sparkline.
    (
        '<polyline points="20,142 67.3,135 114.5,131.5 161.8,121 209.1,124.5 256.4,114 303.6,107 350.9,110.5 398.2,100 445.5,96.5 492.7,89.5 540,86" fill="none" stroke="var(--accent)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
        '<polyline points="{{ repDotPoints }}" fill="none" stroke="var(--accent)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
        "reportes: línea del sparkline de dotación",
    ),
    # El punto final del sparkline (último mes).
    (
        '<circle cx="540" cy="86" r="4" fill="var(--accent)" stroke="var(--surface)" stroke-width="2.5"/>',
        '<circle cx="{{ repDotX }}" cy="{{ repDotY }}" r="4" fill="var(--accent)" stroke="var(--surface)" stroke-width="2.5"/>',
        "reportes: punto final del sparkline",
    ),
    # Las etiquetas de meses del eje x (12 meses reales, no los fijos Ago…Jul).
    (
        '<span>Ago</span><span>Sep</span><span>Oct</span><span>Nov</span><span>Dic</span><span>Ene</span><span>Feb</span><span>Mar</span><span>Abr</span><span>May</span><span>Jun</span><span>Jul</span>',
        '<sc-for list="{{ repDotLabels }}" as="l" hint-placeholder-count="12"><span>{{ l.label }}</span></sc-for>',
        "reportes: etiquetas de meses del sparkline",
    ),
    # Los arcos de la dona de motivos de egreso: se reemplazan los 5 fijos por un sc-for
    # sobre repEgresoArcs (el círculo de fondo, gris, queda como está). React resuelve el
    # namespace SVG de los <circle> del sc-for por el tag, igual que con cualquier elemento.
    (
        '                <circle cx="70" cy="70" r="54" fill="none" stroke="var(--accent)" stroke-width="18" stroke-dasharray="142.5 400"/>\n'
        '                <circle cx="70" cy="70" r="54" fill="none" stroke="var(--accent2)" stroke-width="18" stroke-dasharray="95 400" stroke-dashoffset="-142.5"/>\n'
        '                <circle cx="70" cy="70" r="54" fill="none" stroke="var(--bad)" stroke-width="18" stroke-dasharray="40.7 400" stroke-dashoffset="-237.5"/>\n'
        '                <circle cx="70" cy="70" r="54" fill="none" stroke="var(--warn)" stroke-width="18" stroke-dasharray="33.9 400" stroke-dashoffset="-278.2"/>\n'
        '                <circle cx="70" cy="70" r="54" fill="none" stroke="var(--text3)" stroke-width="18" stroke-dasharray="27.1 400" stroke-dashoffset="-312.1"/>',
        '                <sc-for list="{{ repEgresoArcs }}" as="a" hint-placeholder-count="5"><circle cx="70" cy="70" r="54" fill="none" stroke="{{ a.color }}" stroke-width="18" stroke-dasharray="{{ a.dash }}" stroke-dashoffset="{{ a.offset }}"/></sc-for>',
        "reportes: arcos de la dona de egresos",
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

    # ===== accesibilidad (auditoría 2026-07-21, fase 1) =====
    # Son atributos ARIA/rol sobre elementos que ya existen: es cableado de accesibilidad, no
    # diseño visual, así que va acá y NO al canvas (mismo criterio que rotularCampos/a11yModal).

    # --- MEDIO-04: los filtros son <select> sin nombre accesible; se los rotula ---
    (
        '<select value="{{ empEmpresa }}" onChange="{{ onEmpresa }}" style="{{ selStyle }}">',
        '<select value="{{ empEmpresa }}" onChange="{{ onEmpresa }}" aria-label="Filtrar por empresa" style="{{ selStyle }}">',
        "MEDIO-04: filtro empresa (empleados)",
    ),
    (
        '<select value="{{ empSector }}" onChange="{{ onSector }}" style="{{ selStyle }}">',
        '<select value="{{ empSector }}" onChange="{{ onSector }}" aria-label="Filtrar por sector" style="{{ selStyle }}">',
        "MEDIO-04: filtro sector (empleados)",
    ),
    (
        '<select value="{{ novTipo }}" onChange="{{ onNovTipo }}" style="{{ selStyle }}">',
        '<select value="{{ novTipo }}" onChange="{{ onNovTipo }}" aria-label="Filtrar por tipo de novedad" style="{{ selStyle }}">',
        "MEDIO-04: filtro tipo (novedades)",
    ),
    (
        '<select value="{{ novEstado }}" onChange="{{ onNovEstado }}" style="{{ selStyle }}">',
        '<select value="{{ novEstado }}" onChange="{{ onNovEstado }}" aria-label="Filtrar por estado" style="{{ selStyle }}">',
        "MEDIO-04: filtro estado (novedades)",
    ),

    # --- MEDIO-03: los acordeones de Configuración son <div onClick>: sin rol, sin foco de
    #     teclado, sin aria-expanded. Se los declara button y se les cuelga el handler de tecla
    #     (definido por sección en renderVals). El nombre accesible sale del texto del título. ---
    (
        '<div onClick="{{ cfgUI.alertas.toggle }}" style="display:flex;align-items:flex-start;gap:12px;cursor:pointer;user-select:none">',
        '<div onClick="{{ cfgUI.alertas.toggle }}" role="button" tabindex="0" aria-expanded="{{ cfgUI.alertas.abierta }}" onKeyDown="{{ cfgUI.alertas.toggleKey }}" style="display:flex;align-items:flex-start;gap:12px;cursor:pointer;user-select:none">',
        "MEDIO-03: acordeón parametría de alertas",
    ),
    (
        '<div onClick="{{ cfgUI.notif.toggle }}" style="display:flex;align-items:flex-start;gap:12px;cursor:pointer;user-select:none">',
        '<div onClick="{{ cfgUI.notif.toggle }}" role="button" tabindex="0" aria-expanded="{{ cfgUI.notif.abierta }}" onKeyDown="{{ cfgUI.notif.toggleKey }}" style="display:flex;align-items:flex-start;gap:12px;cursor:pointer;user-select:none">',
        "MEDIO-03: acordeón destinatarios y canales",
    ),
    (
        '<div onClick="{{ cfgUI.empresas.toggle }}" style="display:flex;align-items:center;gap:12px;cursor:pointer;user-select:none;flex:1;min-width:0">',
        '<div onClick="{{ cfgUI.empresas.toggle }}" role="button" tabindex="0" aria-expanded="{{ cfgUI.empresas.abierta }}" onKeyDown="{{ cfgUI.empresas.toggleKey }}" style="display:flex;align-items:center;gap:12px;cursor:pointer;user-select:none;flex:1;min-width:0">',
        "MEDIO-03: acordeón empresas del grupo",
    ),
    (
        '<div onClick="{{ cfgUI.sectores.toggle }}" style="display:flex;align-items:center;gap:12px;cursor:pointer;user-select:none;flex:1;min-width:0">',
        '<div onClick="{{ cfgUI.sectores.toggle }}" role="button" tabindex="0" aria-expanded="{{ cfgUI.sectores.abierta }}" onKeyDown="{{ cfgUI.sectores.toggleKey }}" style="display:flex;align-items:center;gap:12px;cursor:pointer;user-select:none;flex:1;min-width:0">',
        "MEDIO-03: acordeón sectores",
    ),

    # --- MENOR-02: "Cambiar foto" envuelve un <input type=file> con display:none, que no es
    #     alcanzable por teclado. Se lo oculta con la técnica clip (invisible pero enfocable) y
    #     se le da nombre propio, así se llega con Tab y se abre con Enter. ---
    (
        '<input data-foto="input" type="file" accept="image/*" onChange="{{ ficha.onFotoInput }}" style="display:none"/>',
        '<input data-foto="input" type="file" accept="image/*" onChange="{{ ficha.onFotoInput }}" aria-label="Cambiar foto de perfil" style="position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);clip-path:inset(50%);border:0"/>',
        "MENOR-02: input de foto alcanzable por teclado",
    ),

    # --- MENOR-03: el badge del menú muestra el total de novedades; se aclara qué cuenta ---
    (
        '<span class="ceibo-navlbl" style="{{ novBadge }}">{{ novCount }}</span>',
        '<span class="ceibo-navlbl" aria-label="{{ novBadgeAria }}" style="{{ novBadge }}">{{ novCount }}</span>',
        "MENOR-03: aria del badge de novedades",
    ),
]


# ===== invariantes del diseño =====
# El layout móvil vive en el canvas desde el 2026-07-20 (ver el comentario en EDICIONES).
# Eso le sacó a este script su red de seguridad: las inyecciones cortaban si el diseño
# cambiaba, pero una regla CSS que ya está en el export no corta nada.
#
# El modo de falla peligroso no es que el layout se rompa —eso se ve al abrir la app— sino
# que las tarjetas móviles rotulan por POSICIÓN (`nth-child(N)::before{content:"..."}`).
# Si un rediseño reordena, agrega o renombra una columna, el layout sigue impecable y la
# tarjeta muestra "EMPRESA" arriba del sector: datos mal rotulados con cara de correctos.
# Por eso se verifica la cabecera literal, que es la que declara el orden de las columnas.
INVARIANTES_DISENO = [
    {
        "pantalla": "Empleados",
        "head": "ceibo-emp-head",
        "fila": "ceibo-emp-row",
        "cabecera": "<div>EMPLEADO</div><div>EMPRESA</div><div>SECTOR</div>"
                    "<div>PUESTO</div><div>ESTADO</div><div></div>",
        "etiquetas": {2: "Empresa", 3: "Sector", 4: "Puesto", 5: "Estado"},
    },
    {
        "pantalla": "Novedades",
        "head": "ceibo-nov-head",
        "fila": "ceibo-nov-row",
        "cabecera": "<div>TIPO</div><div>EMPLEADO</div><div>FECHA</div>"
                    "<div>CLASIFICACIÓN</div><div>ESTADO</div>",
        "etiquetas": {2: "Empleado", 3: "Fecha", 4: "Clasificación"},
    },
]

# Clases sin cabecera que verificar, pero de las que igual depende el layout/accesibilidad.
CLASES_REQUERIDAS = [
    {"clase": "ceibo-cfg-row", "para": "layout móvil de Configuración"},
    {
        "clase": "ceibo-navlbl",
        "para": "nombre accesible del menú lateral en móvil",
        # No alcanza con que la regla exista: tiene que seguir siendo "oculto solo a la
        # vista". display:none esconde la etiqueta del lector de pantalla y los seis
        # botones del menú vuelven a anunciarse como "botón" a secas (REG-03).
        "prohibido": "display:none",
    },
]


def _reglas_css(plano: str, clase: str) -> list:
    """Cuerpos de las reglas CSS cuyo selector incluye .clase.

    Con borde a la derecha para no confundir `.ceibo-navlbl` con `.ceibo-navlbl-x`:
    un simple `in` daría por presente una regla que en realidad se renombró.
    """
    selector = re.compile(r"\." + re.escape(clase) + r"(?![-\w])")
    return [cuerpo for sel, cuerpo in re.findall(r"([^{}]*)\{([^{}]*)\}", plano)
            if selector.search(sel)]


def verificar_invariantes(html: str) -> None:
    """Corta si el diseño dejó de cumplir lo que el layout móvil asume."""
    plano = "".join(html.split())   # sin espacios: tolera reformateo del CSS
    fallas = []

    for inv in INVARIANTES_DISENO:
        p = inv["pantalla"]
        for clase in (inv["head"], inv["fila"]):
            if f'class="{clase}"' not in html:
                fallas.append(
                    f'{p}: falta class="{clase}" en el markup. El CSS móvil quedó '
                    f"apuntando a nada y la tabla vuelve a ser ilegible en celular.")
            if not _reglas_css(plano, clase):
                fallas.append(
                    f"{p}: no hay reglas CSS para .{clase}. ¿Se borró o se renombró el "
                    f"bloque @media del diseño?")
        if "".join(inv["cabecera"].split()) not in plano:
            fallas.append(
                f"{p}: la cabecera de la tabla cambió. Las etiquetas de la tarjeta móvil "
                f"se asignan por posición, así que reordenar/agregar/renombrar una columna "
                f"las deja rotulando el dato equivocado.\n"
                f"       Esperada: {inv['cabecera']}\n"
                f"       Hay que reajustar los nth-child del @media y esta cabecera.")
        for n, etiqueta in inv["etiquetas"].items():
            regla = f'.{inv["fila"]}>div:nth-child({n})::before{{content:"{etiqueta}"}}'
            if regla not in plano:
                fallas.append(
                    f'{p}: falta la etiqueta móvil de la columna {n} ("{etiqueta}").')

    for req in CLASES_REQUERIDAS:
        clase, para_que = req["clase"], req["para"]
        if f'class="{clase}"' not in html:
            fallas.append(f'falta class="{clase}" en el markup ({para_que}).')
        reglas = _reglas_css(plano, clase)
        if not reglas:
            fallas.append(
                f"no hay reglas CSS para .{clase} ({para_que}); ¿se borró o se renombró?")
        elif req.get("prohibido"):
            malas = [c for c in reglas if req["prohibido"] in c]
            if malas:
                fallas.append(
                    f".{clase} volvió a usar '{req['prohibido']}' ({para_que}). "
                    f"Tiene que quedar oculta solo a la vista (clip/clip-path), o el "
                    f"lector de pantalla pierde el nombre de los botones del menú.")

    if fallas:
        print("\nERROR: el diseño ya no cumple lo que asume el layout móvil.\n")
        for f in fallas:
            print(f"  - {f}")
        sys.exit(
            "\nEstas reglas viven en el canvas (Claude Design), no en build.py. "
            "Revisar el export\ny reajustar el @media correspondiente antes de seguir. "
            "Ver 'invariantes del diseño'\nen este archivo.")
    print(f"  [ok] invariantes del diseño ({len(INVARIANTES_DISENO)} tablas + "
          f"{len(CLASES_REQUERIDAS)} clases)")


# Los assets se publican con el hash de su contenido en el nombre. Antes se llamaban
# siempre `ceibo-api.js` y `support.js`: al actualizar, un navegador con la versión vieja
# en caché podía quedarse con el JS anterior y pedir el index.html nuevo. El resultado no
# era "algo desactualizado" sino la app en blanco —el index nuevo llamaba a una función que
# el JS viejo no tenía y el render entero moría—. Con el hash en el nombre, cada index.html
# pide exactamente los archivos con los que se construyó: la mezcla ya no puede ocurrir.
# El único archivo con nombre fijo es index.html, y quedarse con uno viejo solo sirve la
# versión anterior completa y coherente, que es una falla aceptable.
ASSETS = [
    ("support.js", lambda: DESIGN / "support.js"),
    ("ceibo-api.js", lambda: RAIZ / "integration" / "ceibo-api.js"),
]


def escribir_assets(html: str) -> str:
    """Copia los assets con hash en el nombre y reescribe sus <script> en el HTML."""
    vigentes = set()
    for nombre, origen in ASSETS:
        datos = origen().read_bytes()
        h = hashlib.sha256(datos).hexdigest()[:10]
        base, ext = nombre.rsplit(".", 1)
        hasheado = f"{base}.{h}.{ext}"
        (DIST / hasheado).write_bytes(datos)
        vigentes.add(hasheado)
        ancla = f'<script src="./{nombre}"></script>'
        if ancla not in html:
            sys.exit(f"ERROR: no se encontró el <script> de {nombre} para hashear. Revisar build.py")
        html = html.replace(ancla, f'<script src="./{hasheado}"></script>', 1)
        print(f"  [ok] asset {nombre} -> {hasheado}")

    # Borrar versiones anteriores: si no, dist/ va juntando un archivo por cada build y no
    # se distingue cuál está en uso. Solo se tocan los que matchean el patrón hasheado.
    patron = re.compile(r"^(support|ceibo-api)\.[0-9a-f]{10}\.js$")
    for viejo in DIST.iterdir():
        if viejo.name not in vigentes and patron.match(viejo.name):
            viejo.unlink()
            print(f"  [--] asset viejo removido: {viejo.name}")
    # Los nombres sin hash de builds anteriores también sobran y confunden.
    for nombre, _ in ASSETS:
        obsoleto = DIST / nombre
        if obsoleto.exists():
            obsoleto.unlink()
            print(f"  [--] asset sin hash removido: {nombre}")
    return html


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

    verificar_invariantes(html)

    for ancla, reemplazo, desc in EDICIONES:
        if ancla not in html:
            sys.exit(f"ERROR: ancla no encontrada [{desc}]. ¿Cambió el diseño? Revisar build.py")
        html = html.replace(ancla, reemplazo, 1)
        print("  [ok] "+desc)

    DIST.mkdir(exist_ok=True)
    html = escribir_assets(html)
    (DIST / "index.html").write_text(html, encoding="utf-8")
    print(f"\nOK -> {DIST / 'index.html'}")
    print("Servir:  cd dist && python -m http.server 8080")


if __name__ == "__main__":
    main()
