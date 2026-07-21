/* ============================================================================
 * Ceibo · Capa de integración con el backend Django (Gestión RRHH)
 * ----------------------------------------------------------------------------
 * Esta capa es lo ÚNICO que se escribe a mano. El diseño (design/Ceibo RRHH.dc.html)
 * se baja de Claude Design y NO se edita; build.py le inyecta shims delgados que
 * llaman a `window.CeiboAPI.*` (definido acá). Así un rediseño se re-cablea solo.
 *
 * Los inputs del form de alta NO tienen binding → se leen/escriben del DOM por
 * ETIQUETA (robusto al orden y a campos nuevos), scopeado a [data-modal="alta"].
 * ==========================================================================*/
(function () {
  "use strict";

  var CONFIG = {
    API: "http://localhost:8000/api/v1",
  };

  // Sesión. El access vive solo en memoria; el refresh se persiste en sessionStorage para
  // que un F5 no eche al usuario, y muere al cerrar la pestaña (en una PC compartida de
  // oficina, localStorage dejaría la sesión abierta para el siguiente que la use).
  var _token = null, _refresh = null, _perfil = null;
  var CLAVE_SESION = "ceibo.refresh";
  // Lo llama el cableado para volver a la pantalla de login cuando la sesión muere sola
  // (refresh vencido o revocado). Sin esto, la app quedaba mostrando datos viejos y cada
  // acción fallaba con un 401 silencioso.
  var _onSesionVencida = null;

  function guardarRefresh(valor) {
    _refresh = valor || null;
    try {
      if (valor) sessionStorage.setItem(CLAVE_SESION, valor);
      else sessionStorage.removeItem(CLAVE_SESION);
    } catch (e) {
      // Modo incógnito estricto o storage bloqueado: la sesión sigue viva en memoria,
      // solo que no sobrevive al F5. No es motivo para romper el login.
      console.warn("[ceibo] sessionStorage no disponible; la sesión no sobrevive al refresco");
    }
  }

  function limpiarSesion() {
    _token = null;
    _perfil = null;
    guardarRefresh(null);
  }
  var _empresaByName = {}, _empresaById = {};
  var _sectorByName = {}, _sectorById = {};
  var _puestoByName = {}, _puestoById = {};
  var _rawEmpleados = [];
  var _empById = {};              // id → { name, empresa } (para adaptar novedades)
  // relación laboral → nombre de empresa. La novedad guarda de QUÉ relación es, así que la
  // etiqueta sale de ahí y no de la relación activa del empleado (ver adaptNov).
  var _empresaByRelacionId = {};
  var _tipoNovByCodigo = {};      // codigo → tipo de novedad (con flags)
  var _novRawById = {};           // id → novedad cruda del backend (para precargar edición)
  var _tipoDocByNombre = {};      // nombre → tipo de documento (el select del modal da el nombre)
  var _docsByEmp = {};            // empleado id → documentos crudos (para precargar la edición)

  // ---------- HTTP ----------
  function auth() { return { Authorization: "Bearer " + _token }; }
  // El access token dura 15 min (SIMPLE_JWT). Se renueva con el refresh ante un 401,
  // así una sesión de trabajo larga no muere con "token inválido" a mitad de una acción.
  async function refreshToken() {
    if (!_refresh) return false;
    var r = await fetch(CONFIG.API + "/auth/token/refresh/", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh: _refresh }),
    });
    if (!r.ok) { limpiarSesion(); return false; }
    var d = await r.json().catch(function () { return {}; });
    if (!d.access) { limpiarSesion(); return false; }
    _token = d.access;
    if (d.refresh) guardarRefresh(d.refresh);  // ROTATE_REFRESH_TOKENS=True → llega uno nuevo
    return true;
  }
  // fetch con Authorization y reintento único ante 401 (access vencido → refresh → retry).
  async function authedFetch(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, opts.headers, auth());
    var r = await fetch(url, opts);
    if (r.status === 401) {
      if (await refreshToken()) {
        opts.headers = Object.assign({}, opts.headers, auth());
        r = await fetch(url, opts);
      } else if (_onSesionVencida) {
        // El refresh ya no sirve: la sesión terminó de verdad. Se avisa una sola vez
        // (limpiarSesion() ya corrió dentro de refreshToken) para volver al login en vez
        // de dejar la app mostrando datos viejos que ya nadie puede actualizar.
        _onSesionVencida();
      }
    }
    return r;
  }
  function flattenErrs(obj) {
    var out = [];
    Object.keys(obj).forEach(function (k) {
      var v = obj[k];
      if (Array.isArray(v)) out.push(v.join(" "));
      else if (v && typeof v === "object") out = out.concat(flattenErrs(v));
      else out.push(String(v));
    });
    return out;
  }
  async function jget(path) {
    var r = await authedFetch(CONFIG.API + path, {});
    if (!r.ok) throw new Error("GET " + path + " → " + r.status);
    return r.json();
  }
  async function jsend(method, path, body) {
    var r = await authedFetch(CONFIG.API + path, {
      method: method,
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    var data = await r.json().catch(function () { return {}; });
    if (!r.ok) {
      var msg;
      if (data.campos && Object.keys(data.campos).length) {
        msg = flattenErrs(data.campos).join(" · ");   // aplana errores anidados (relacion.x)
      } else {
        msg = data.detalle || ("Error " + r.status);
      }
      throw new Error(msg);
    }
    return data;
  }
  // Chequea r.ok como jget: sin eso, un 401/429/500 en cualquier página dejaba `d.results`
  // undefined y la paginación seguía como si nada → la UI mostraba "0 empleados" o una lista
  // a medias, sin un solo error visible. Un fallo tiene que romper ruidoso, no mentir.
  // `page_size` tope 100 (max_page_size del backend): pedir 200 se clampeaba en silencio.
  async function getAllPages(path) {
    var rows = [], url = CONFIG.API + path;
    while (url) {
      var r = await authedFetch(url, {});
      if (!r.ok) throw new Error("GET " + path + " → " + r.status);
      var d = await r.json();
      rows = rows.concat(d.results || []);
      url = d.next;
    }
    return rows;
  }

  // ---------- formato ----------
  function fmtISOtoDMY(iso) { return iso ? iso.split("-").reverse().join("/") : ""; }
  function parseFecha(s) {
    if (!s) return null;
    s = String(s).trim();
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;            // ya es ISO (input type="date")
    var p = s.split("/");
    if (p.length !== 3) return null;
    var d = p[0].padStart(2, "0"), m = p[1].padStart(2, "0"), y = p[2];
    if (y.length !== 4) return null;
    return y + "-" + m + "-" + d;                            // dd/mm/aaaa → ISO
  }
  // Hora LOCAL, no UTC: toISOString() devuelve el día UTC y en Argentina (UTC-3) de 21:00 a
  // 23:59 eso es "mañana" — una baja cargada a la noche quedaba fechada al día siguiente.
  function todayISO() {
    var d = new Date();
    var mm = String(d.getMonth() + 1).padStart(2, "0"), dd = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + mm + "-" + dd;
  }
  function splitName(full) {
    var parts = (full || "").trim().split(/\s+/);
    if (parts.length <= 1) return { nombre: parts[0] || "", apellido: "" };
    return { nombre: parts[0], apellido: parts.slice(1).join(" ") };
  }
  // Un ingreso reciente no es "1 años": bajo el año se informa en meses (y bajo el mes,
  // en días), porque el período de prueba se cuenta en meses y redondearlo a un año
  // falsea el dato justo cuando más importa.
  function anios(rel) {
    if (!rel || rel.antiguedad_en_dias == null) return "";
    var dias = rel.antiguedad_en_dias;
    if (dias < 30) return dias === 1 ? "1 día" : dias + " días";
    if (dias < 365) {
      // Tope en 11: a 364 días, floor(364/30) daría "12 meses", que se lee como el año
      // cumplido —y el año cumplido dispara antigüedad—. Bajo los 365 nunca decimos 12.
      var meses = Math.min(11, Math.floor(dias / 30));
      return meses === 1 ? "1 mes" : meses + " meses";
    }
    var n = Math.floor(dias / 365);
    return n === 1 ? "1 año" : n + " años";
  }
  // El backend expone `nombre_completo` como "Apellido, Nombre" (Empleado.nombre_completo),
  // y por ahí llegan novedades, vencimientos y alertas del día. `adapt()`, en cambio, arma
  // "Nombre Apellido". Convivían los dos formatos en la misma pantalla —"Carla Benítez"
  // arriba y "Benítez, Carla" abajo— según de qué endpoint viniera el dato. Se normaliza
  // todo a "Nombre Apellido" al entrar, que es como se lee a una persona.
  function nombreNatural(s) {
    s = (s || "").trim();
    var i = s.indexOf(",");
    if (i < 0) return s;
    var apellido = s.slice(0, i).trim(), nombre = s.slice(i + 1).trim();
    return nombre && apellido ? nombre + " " + apellido : s;
  }
  function stripAccents(s) { return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, ""); }
  function normLabel(s) { return stripAccents((s || "").replace(/\s*·\s*$/, "").trim().toLowerCase()); }

  // enums del backend (texto del <select> del diseño → valor de la API, y reverso)
  var MOTIVO = {
    "Renuncia": "RENUNCIA", "Fin de contrato": "FIN_CONTRATO", "Despido": "DESPIDO",
    "Mudanza": "MUDANZA", "Jubilación": "JUBILACION", "Jubilacion": "JUBILACION", "Otro": "OTRO",
  };
  var EDU = {
    "Primario incompleto": "PRIMARIO_INCOMPLETO", "Primario completo": "PRIMARIO_COMPLETO",
    "Secundario incompleto": "SECUNDARIO_INCOMPLETO", "Secundario completo": "SECUNDARIO_COMPLETO",
    "Terciario": "TERCIARIO", "Universitario": "UNIVERSITARIO",
  };
  var JORNADA = {
    "Completa (8 h)": "COMPLETA_8H", "Reducida (6 h)": "REDUCIDA_6H",
    "Media jornada (4 h)": "MEDIA_4H", "Turnos rotativos": "ROTATIVA",
  };
  var EDU_REV = {}, JORNADA_REV = {};
  Object.keys(EDU).forEach(function (k) { EDU_REV[EDU[k]] = k; });
  Object.keys(JORNADA).forEach(function (k) { JORNADA_REV[JORNADA[k]] = k; });

  // Novedades: texto del <select> del diseño → código/valor de la API.
  var TIPONOV = {
    "Falta": "FALTA", "Licencia médica": "LICENCIA_MEDICA", "Accidente": "ACCIDENTE",
    "Vacaciones": "VACACIONES", "Permiso": "PERMISO", "Horas extra": "HORAS_EXTRA",
  };
  var TIPONOV_REV = {};  // codigo → etiqueta del <select> (para precargar en edición)
  Object.keys(TIPONOV).forEach(function (k) { TIPONOV_REV[TIPONOV[k]] = k; });
  var CLASIF = { "Justificada": "JUSTIFICADA", "Injustificada": "INJUSTIFICADA" };
  var CLASIF_REV = { "JUSTIFICADA": "Justificada", "INJUSTIFICADA": "Injustificada" };
  // Estado elegido en el alta → endpoint de transición (los que hoy existen en el backend).
  // "Registrada" es el estado natural; "En proceso"/"Cerrada" aún no tienen endpoint.
  var ESTADONOV = { "Aprobada": "aprobar", "Rechazada": "rechazar", "Anulada": "anular" };

  function fmtRango(desdeISO, hastaISO) {
    var d = fmtISOtoDMY(desdeISO);
    if (!hastaISO || hastaISO === desdeISO) return d;
    return d + " → " + fmtISOtoDMY(hastaISO);
  }

  // Dos fechas locales, nunca `new Date(iso)`: ese constructor interpreta "2026-07-16" como
  // medianoche UTC, y restarle `new Date()` (hora local) mezclaba dos husos. En Argentina
  // (UTC-3) la cuenta daba negativa el mismo día del vencimiento, así que un documento que
  // vence HOY se pintaba VENCIDO en rojo durante todo el día, cuando todavía es válido.
  // `diasEntreISO` es inclusive (hoy→hoy = 1), de ahí el −1 para tener la diferencia real.
  function docEstado(iso) {
    if (!iso) return "ok";
    var dias = diasEntreISO(todayISO(), iso) - 1;
    if (dias < 0) return "bad";      // venció: ayer o antes
    if (dias <= 30) return "warn";   // vence hoy o dentro del mes
    return "ok";
  }

  // ---------- toast (sin alert(), que bloquea la automatización) ----------
  function showToast(msg, kind) {
    var col = kind === "error"
      ? { bg: "#3b1218", bd: "#F87171", fg: "#FCA5A5" }
      : { bg: "#0f2b26", bd: "#2DD4BF", fg: "#5EEAD4" };
    var t = document.createElement("div");
    t.textContent = msg;
    t.style.cssText =
      "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);z-index:99999;" +
      "background:" + col.bg + ";border:1px solid " + col.bd + ";color:" + col.fg + ";" +
      "font:600 13.5px/1.4 'Hanken Grotesk',-apple-system,sans-serif;padding:12px 20px;border-radius:12px;" +
      "box-shadow:0 12px 40px rgba(0,0,0,.45);max-width:80vw;opacity:1;transition:opacity .3s";
    document.body.appendChild(t);
    setTimeout(function () { t.style.opacity = "0"; setTimeout(function () { t.remove(); }, 320); }, kind === "error" ? 4500 : 2600);
  }

  // ---------- adaptador empleado (API → shape del diseño) ----------
  function adapt(e) {
    var rels = e.relaciones || [];
    var activa = rels.find(function (r) { return r.estado === "ACTIVA"; }) || rels[0] || {};
    var historial = rels.map(function (r) {
      return {
        puesto: _puestoById[r.puesto] || "—", empresa: _empresaById[r.empresa] || "—",
        rango: fmtISOtoDMY(r.fecha_ingreso) + " — " + (r.estado === "ACTIVA" ? "Actualidad" : fmtISOtoDMY(r.fecha_egreso)),
        estado: r.estado === "ACTIVA" ? "Activo" : "Baja", motivo: r.motivo_egreso || "",
      };
    });
    return {
      id: e.id, name: (e.nombre + " " + e.apellido).trim(), dni: e.dni,
      empresa: _empresaById[activa.empresa] || "—", sector: _sectorById[activa.sector] || "—",
      puesto: _puestoById[activa.puesto] || "—", estado: e.activo ? "activo" : "inactivo",
      ingreso: fmtISOtoDMY(activa.fecha_ingreso), antig: anios(activa),
      email: e.email || "", tel: e.telefono || "", nac: fmtISOtoDMY(e.fecha_nacimiento),
      domicilio: e.direccion || "", cuil: e.cuil || "",
      contacto_emergencia: e.contacto_emergencia || "", obra_social: e.obra_social || "",
      art: e.art || "", observaciones: e.observaciones || "", id_huella: e.id_huella || "",
      educacion: e.educacion || "", exento_marcacion: !!e.exento_marcacion,
      jornada_legal: activa.jornada_legal || "",
      historial: historial, docs: [],
      // metadatos para el cableado:
      _relacionActivaId: activa.id || null, _empresaId: activa.empresa || null,
      _sectorId: activa.sector || null, _puestoId: activa.puesto || null,
      _jornadaLegal: activa.jornada_legal || "", _tipoContrato: activa.tipo_contrato || "",
      _nacISO: e.fecha_nacimiento || "", _ingresoISO: activa.fecha_ingreso || "",
    };
  }

  // ---------- adaptador novedad (API → shape del diseño) ----------
  // El diseño espera { id, tipo, emp, empresa, fecha, estado, clasif, praxis, cert, horas,
  // prorrogas[], madreDesde/Hasta/Motivo }. Las prórrogas se adjuntan agrupando por madre.
  function adaptNov(n) {
    var emp = _empById[n.empleado] || {};
    var tipo = _tipoNovByCodigo[n.tipo_novedad_codigo] || {};
    var cert = n.certificado_recibido_en ? "Presentado" : (tipo.requiere_certificado ? "Pendiente" : "—");
    var out = {
      id: n.id,
      tipo: n.tipo_novedad_nombre,
      emp: emp.name || nombreNatural(n.empleado_nombre) || "—",
      // La empresa de la NOVEDAD, no la del empleado hoy: quien pasó de una empresa del
      // grupo a la otra tenía sus novedades viejas etiquetadas con la actual. Se cae a la
      // relación activa solo si la novedad no dice de qué relación es (dato opcional).
      empresa: _empresaByRelacionId[n.relacion_laboral] || emp.empresa || "—",
      fecha: fmtRango(n.fecha_desde, n.fecha_hasta),
      estado: n.estado_display,
      clasif: CLASIF_REV[n.clasificacion] || "",
      praxis: !!n.requiere_praxis,
      cert: cert,
      horas: n.cantidad_horas != null ? Number(n.cantidad_horas) : null,
      prorrogas: [],
      _codigo: n.tipo_novedad_codigo,
      _empId: n.empleado,
    };
    // Con fecha_hasta, el detalle arma la línea de tiempo (madre) y calcula días/vigencia.
    if (n.fecha_hasta) {
      out.madreDesde = fmtISOtoDMY(n.fecha_desde);
      out.madreHasta = fmtISOtoDMY(n.fecha_hasta);
      out.madreMotivo = n.motivo || n.tipo_novedad_nombre;
    }
    return out;
  }

  async function getOrCreatePuesto(nombre) {
    nombre = (nombre || "").trim();
    if (!nombre) return null;
    var key = nombre.toLowerCase();
    if (_puestoByName[key]) return _puestoByName[key];
    var p = await jsend("POST", "/puestos/", { nombre: nombre });
    _puestoByName[key] = p.id; _puestoById[p.id] = p.nombre;
    return p.id;
  }
  // Busca una persona por DNI EXACTO (el `q` del backend es icontains, así que se filtra
  // el match exacto acá). Devuelve el empleado crudo (con `relaciones`/`activo`) o null.
  // Es la clave del alta: si el DNI ya existe, no es un alta nueva sino un reingreso.
  async function findEmpleadoByDni(dni) {
    if (!dni) return null;
    var arr = await getAllPages("/empleados/?q=" + encodeURIComponent(dni) + "&page_size=50");
    return arr.find(function (e) { return String(e.dni) === String(dni); }) || null;
  }

  // ---------- form de alta: lectura/escritura por etiqueta ----------
  function altaModal() { return document.querySelector('[data-modal="alta"]'); }
  // Etiqueta de un input: sube por los ancestros hasta el wrapper del campo y toma
  // el primer <div> "de texto" (sin input adentro). Robusto a envolturas extra
  // (p. ej. el input type="date" del diseño tiene un wrapper de calendario).
  // El <div> de etiqueta de un input (subiendo hasta 4 niveles). Devolver el nodo —no solo
  // el texto— permite renombrar la etiqueta en runtime (ver prefill de prórroga).
  function labelDivOf(el) {
    var node = el;
    for (var i = 0; i < 4 && node; i++) {
      node = node.parentElement;
      if (!node) break;
      var divs = node.querySelectorAll(":scope > div");
      for (var j = 0; j < divs.length; j++) {
        var d = divs[j];
        if (d.querySelector("input,select,textarea")) continue;   // no es la etiqueta
        var txt = d.textContent.trim();
        if (txt && txt.length <= 32) return d;
      }
    }
    return null;
  }
  function labelFor(el) { var d = labelDivOf(el); return d ? d.textContent.trim() : ""; }
  // Lee un modal a un mapa etiqueta-normalizada → elemento (primer input por etiqueta gana).
  function readModalForm(sel) {
    var m = document.querySelector(sel);
    if (!m) throw new Error("modal no encontrado: " + sel);
    var map = {};
    m.querySelectorAll("input,select,textarea").forEach(function (el) {
      var key = normLabel(labelFor(el));
      if (key && map[key] == null) map[key] = el;
    });
    return map;
  }
  function readAltaForm() { return readModalForm('[data-modal="alta"]'); }

  // ---------- accesibilidad de los modales (BUG-12) ----------
  // El markup ya declara role="dialog"/aria-modal (eso vive en el canvas). Lo que no se
  // puede declarar es el comportamiento: al abrir, el foco sigue en el botón que quedó
  // detrás del overlay, así que un usuario de teclado tabula por la pantalla tapada. Acá
  // se mueve el foco adentro, se lo encierra y se lo devuelve al cerrar.
  var _focoPrevio = null, _trapHandler = null;
  function focoAtrapado(sel) {
    var m = document.querySelector(sel);
    if (!m) return;
    _focoPrevio = document.activeElement;
    var focusables = function () {
      return Array.prototype.filter.call(
        m.querySelectorAll('a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])'),
        function (el) { return !el.disabled && el.offsetParent !== null; }
      );
    };
    var f = focusables();
    // El primer campo real, no la "✕": quien abre un alta quiere escribir, no cerrar.
    var primero = f.find(function (el) { return /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName); }) || f[0];
    if (primero) primero.focus();
    _trapHandler = function (e) {
      if (e.key === "Escape") { var x = m.querySelector("button"); if (x) x.click(); return; }
      if (e.key !== "Tab") return;
      var lista = focusables();
      if (!lista.length) return;
      var ini = lista[0], fin = lista[lista.length - 1];
      // Sin esto el Tab se escapa a la página de atrás y el usuario no encuentra el camino
      // de vuelta al diálogo.
      if (e.shiftKey && document.activeElement === ini) { e.preventDefault(); fin.focus(); }
      else if (!e.shiftKey && document.activeElement === fin) { e.preventDefault(); ini.focus(); }
    };
    m.addEventListener("keydown", _trapHandler);
  }
  function focoDevuelto() {
    if (_focoPrevio && _focoPrevio.focus) _focoPrevio.focus();
    _focoPrevio = null;
    _trapHandler = null;
  }
  // Red de seguridad para los nombres accesibles: el canvas rotula con <div>, no con
  // <label for>, así que un lector de pantalla anunciaría "cuadro de edición" y nada más.
  // Se copia la etiqueta visible al aria-label de cada control del modal.
  function rotularCampos(sel) {
    var m = document.querySelector(sel);
    if (!m) return;
    m.querySelectorAll("input,select,textarea").forEach(function (el) {
      if (el.getAttribute("aria-label")) return;
      var txt = labelFor(el).replace(/\s*·\s*$/, "").trim();
      if (txt) el.setAttribute("aria-label", txt);
    });
  }

  // ---------- campos de la ficha que el guardado NO toca ----------
  // El PATCH de edición va contra ActualizarEmpleadoSerializer, que expone SOLO datos de la
  // persona. El DNI no está entre ellos, y todo lo que cuelga de la relación laboral
  // (empresa, sector, puesto, ingreso, jornada) se cambia por sus propios endpoints: no hay
  // PATCH de relación, solo crear y finalizar. Con los campos habilitados el form aceptaba
  // ediciones que el PATCH descartaba sin decir nada —se guardaba "bien" y el sector seguía
  // igual—, así que se bloquean y se explica el motivo en pantalla.
  var EMPRESA_LOCK_MSG =
    "La empresa no se edita desde la ficha. Para mover al empleado a otra empresa, " +
    "registrá su salida (baja) y luego su reingreso.";
  var RELACION_LOCK_MSG =
    "Sector, puesto, fecha de ingreso y jornada son parte de la relación laboral y no se " +
    "editan desde la ficha: se cambian registrando la baja y el reingreso.";
  var DNI_LOCK_MSG = "El DNI identifica a la persona y no se edita desde la ficha.";
  var ESTADO_LOCK_MSG =
    "El estado no se elige a mano: sale de la relación laboral (activo mientras haya una " +
    "relación ACTIVA). Se cambia dando de baja o registrando el reingreso.";
  // Campos de la relación laboral, por etiqueta normalizada (las claves de readAltaForm).
  var CAMPOS_RELACION = ["sector", "puesto", "fecha de ingreso", "jornada legal"];

  function lockCampo(el, msg) {
    if (!el) return;
    el.disabled = true;
    el.title = msg;
    el.style.opacity = "0.55";
    el.style.cursor = "not-allowed";
    // "Fecha de ingreso" son DOS inputs: el de texto y un date picker superpuesto que lo
    // escribe (onChange={{ pickDate }}). Deshabilitar solo el de texto dejaba vivo el
    // calendario, así que el campo "bloqueado" se seguía editando con dos clics.
    var wrap = el.parentElement;
    if (wrap) {
      wrap.querySelectorAll('input[type="date"]').forEach(function (d) {
        d.disabled = true;
        d.style.cursor = "not-allowed";
      });
    }
  }
  function unlockCampo(el) {
    if (!el) return;
    el.disabled = false;
    el.title = "";
    el.style.opacity = "";
    el.style.cursor = "";
    var wrap = el.parentElement;
    if (wrap) {
      wrap.querySelectorAll('input[type="date"]').forEach(function (d) {
        d.disabled = false;
        d.style.cursor = "pointer";
      });
    }
  }
  // Un `title` no lo lee nadie: si los campos quedan grises sin explicación visible, el
  // usuario solo ve una ficha rota. El motivo va arriba de la sección que se bloqueó.
  function notaEdicion(f) {
    var ref = f["sector"] || f["empresa"] || f["puesto"];
    var grid = ref && ref.closest ? ref.closest("div[style*='grid-template-columns']") : null;
    if (!grid || !grid.parentElement) return;
    var cont = grid.parentElement;
    if (cont.querySelector("[data-ceibo-nota]")) return;   // no duplicar si se reabre
    var nota = document.createElement("div");
    nota.setAttribute("data-ceibo-nota", "1");
    nota.textContent =
      "Los datos laborales no se editan desde la ficha: se cambian registrando la baja y " +
      "el reingreso. Acá se guardan solo los datos personales, de contacto y de cobertura.";
    nota.style.cssText =
      "font-size:11.5px;line-height:1.45;color:var(--text3);background:var(--surface);" +
      "border:1px solid var(--border2);border-radius:9px;padding:9px 11px;margin-bottom:12px";
    cont.insertBefore(nota, grid);
  }
  function quitarNotaEdicion() {
    var m = document.querySelector('[data-modal="alta"]');
    if (!m) return;
    m.querySelectorAll("[data-ceibo-nota]").forEach(function (n) { n.remove(); });
  }
  function unlockEmpresa(el) {
    unlockCampo(el);
    if (!el) return;
    // Antepone una opción vacía y la deja seleccionada, para forzar una elección consciente.
    if (el.tagName === "SELECT") {
      var first = el.options[0];
      if (!first || first.value !== "") {
        var opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Seleccionar empresa…";
        el.insertBefore(opt, el.firstChild);
      }
      el.value = "";
    }
  }

  // ---------- helpers de novedad ----------
  var ESTADO_NOV_LOCK_MSG =
    "El estado no se edita acá: se cambia con Aprobar, Rechazar o Anular desde el detalle " +
    "de la novedad.";
  // El canvas ofrece los seis estados del dominio, pero el backend solo tiene endpoint para
  // aprobar/rechazar/anular. Elegir "En proceso" o "Cerrada" no hacía nada: la novedad
  // quedaba Registrada y nadie avisaba. Se retiran del <select> hasta que existan, que es
  // más honesto que aceptarlas y perderlas.
  function podarEstadosNov(sel) {
    if (!sel || sel.tagName !== "SELECT") return;
    Array.prototype.slice.call(sel.options).forEach(function (o) {
      var v = o.value || o.textContent;
      if (v !== "Registrada" && !ESTADONOV[v]) o.remove();
    });
    sel.value = "Registrada";
  }
  // Resuelve el id de empleado por nombre escrito (autocompletado); null si no está en la base.
  function empIdByName(name) {
    var key = normLabel(name);
    if (!key) return null;
    var found = _rawEmpleados.find(function (e) {
      return normLabel((e.nombre + " " + e.apellido).trim()) === key;
    });
    return found ? found.id : null;
  }
  function addDaysISO(iso, n) {
    var p = iso.split("-");
    var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    d.setDate(d.getDate() + n);
    var mm = String(d.getMonth() + 1).padStart(2, "0"), dd = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + mm + "-" + dd;
  }
  function diasEntreISO(aISO, bISO) {  // inclusive
    var pa = aISO.split("-"), pb = bISO.split("-");
    var da = new Date(Number(pa[0]), Number(pa[1]) - 1, Number(pa[2]));
    var db = new Date(Number(pb[0]), Number(pb[1]) - 1, Number(pb[2]));
    return Math.round((db - da) / 86400000) + 1;
  }
  // "Fecha fin estimada" = fecha_desde + (días − 1), inclusive (misma convención que el back).
  function recomputeFinEstimada() {
    var f = readModalForm('[data-modal="altanov"]');
    var desde = parseFecha(f["fecha"] ? f["fecha"].value : "");
    var dias = parseInt(f["dias"] ? f["dias"].value : "", 10);
    var fin = f["fecha fin estimada"];
    if (!desde || !dias || dias < 1 || !fin) return;
    fin.value = fmtISOtoDMY(addDaysISO(desde, dias - 1));
  }

  // ============================ API pública ============================
  // ---------- adaptador dashboard (API → vars del diseño) ----------
  function fmtNum1(v) { return (Math.round((v || 0) * 10) / 10).toFixed(1).replace(".", ","); }
  function kpiDelta(n, goodWhenUp) {
    if (!n) return { txt: "—", style: "font-size:12px;font-weight:600;color:var(--text3)" };
    var up = n > 0, good = goodWhenUp ? up : !up;
    var color = good ? "var(--ok)" : "var(--bad)";
    return { txt: (up ? "▲ " : "▼ ") + Math.abs(n), style: "font-size:12px;font-weight:600;color:" + color };
  }
  // Íconos SVG: se reusan los del diseño (mockMetrics), en el mismo orden de tarjetas.
  function dashMetrics(d, mockMetrics) {
    mockMetrics = mockMetrics || [];
    var mes = (d.periodo && d.periodo.mes_label) || "";
    var cards = [
      { key: "activos", label: "Empleados activos", sub: "vs. mes anterior", goodUp: true },
      { key: "ingresos_mes", label: "Ingresos del mes", sub: mes, goodUp: true },
      { key: "egresos_mes", label: "Egresos del mes", sub: mes, goodUp: false },
      { key: "ausentismo_mes", label: "Ausentismo del mes", sub: mes, goodUp: false },
    ];
    return cards.map(function (c, i) {
      var m = d[c.key] || { valor: 0, delta: 0 };
      var dl = kpiDelta(m.delta, c.goodUp);
      return {
        label: c.label, value: String(m.valor), sub: c.sub,
        delta: dl.txt, deltaStyle: dl.style,
        icon: (mockMetrics[i] && mockMetrics[i].icon) || "",
      };
    });
  }
  function dashRank(d) {
    var arr = d.ranking_faltas || [];
    var max = arr.reduce(function (a, r) { return Math.max(a, r.total); }, 0) || 1;
    return arr.map(function (r, i) {
      return {
        rank: i + 1, name: r.nombre, emp: r.empresa, val: r.total,
        bar: "height:100%;width:" + Math.round(r.total / max * 100) + "%;border-radius:5px;background:var(--accent)",
      };
    });
  }
  // Sparkline sobre el viewBox 0 0 560 190 del diseño (x: 20→540, y: 40→160).
  function dashRotacion(d, rotState) {
    var rot = d.rotacion || {}, serie = rot.serie || [];
    var pick = (rotState === "a") ? (rot.anual || {}) : (rot.mensual || {});
    var dpts = pick.delta_pts || 0, same = !dpts, up = dpts > 0;
    var color = same ? "var(--text3)" : (up ? "var(--bad)" : "var(--ok)");
    var deltaTxt = same ? "sin cambios" : ((up ? "▲ " : "▼ ") + fmtNum1(Math.abs(dpts)) + " pts");
    var vals = serie.map(function (p) { return p.valor; });
    var vmin = Math.min.apply(null, vals.concat([0])), vmax = Math.max.apply(null, vals.concat([0]));
    var range = (vmax - vmin) || 1, n = serie.length || 1;
    var pts = serie.map(function (p, i) {
      var x = 20 + (n > 1 ? i * (520 / (n - 1)) : 0);
      var y = 160 - ((p.valor - vmin) / range) * 120;
      return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 };
    });
    var pointsStr = pts.map(function (p) { return p.x + "," + p.y; }).join(" ");
    var first = pts[0] || { x: 20, y: 100 }, last = pts[pts.length - 1] || { x: 540, y: 100 };
    var area = "M" + first.x + ",160 L" + pointsStr.split(" ").join(" L") + " L" + last.x + ",160 Z";
    return {
      rotValor: fmtNum1(pick.valor) + "%", rotDelta: deltaTxt,
      rotDeltaStyle: "font-size:12px;color:" + color + ";font-weight:600",
      rotPeriodoLbl: (rotState === "a") ? "últimos 12 meses" : "vs. mes anterior",
      rotPoints: pointsStr, rotArea: area, rotDotX: last.x, rotDotY: last.y,
      rotLabels: serie.map(function (p) { return { label: p.label }; }),
    };
  }

  // El input "Archivo certificado" del canvas es un <input type=file> pelado: sin `accept`
  // el explorador ofrece cualquier cosa y el rechazo llega recién del backend. Se acota
  // acá (comportamiento, no diseño) a lo mismo que aceptan los otros respaldos.
  function prepararInputCertificado(f) {
    var el = f["archivo certificado"];
    if (!el || el.type !== "file") return;
    el.setAttribute("accept", ".pdf,.jpg,.jpeg,.png,.webp,.heic");
  }

  // Sube el certificado elegido en el form de novedad como respaldo de la novedad recién
  // guardada. La novedad YA existe cuando esto corre: si el archivo falla, hay que decir
  // con todas las letras que el registro se guardó, o el usuario reintenta el alta y
  // termina con la novedad duplicada (mismo criterio que la transición de estado).
  async function adjuntarCertificado(novId, file, hechoTxt) {
    try {
      await window.CeiboAPI.subirAdjunto(novId, file);
    } catch (e) {
      throw new Error(hechoTxt + ", pero el certificado no se pudo adjuntar: " + e.message +
        ". No la cargues de nuevo: subí el archivo desde el detalle de la novedad.");
    }
  }

  window.CeiboAPI = {
    toast: showToast,

    // Se llama al abrir cada modal: rotula los campos y encierra el foco (ver arriba).
    a11yModal(sel) { rotularCampos(sel); focoAtrapado(sel); },
    a11yCerrar: focoDevuelto,

    // Cambio de módulo = pantalla nueva: se entra por arriba. El scroll vive en <main>
    // (no en window), así que scrollTo() del navegador no sirve.
    // Se hace dos veces a propósito: ya, y de nuevo después del re-render, porque el
    // re-render conserva la posición del módulo anterior. Con setTimeout y no con
    // requestAnimationFrame: rAF queda suspendido en pestañas ocultas, así que navegar
    // con la pestaña en segundo plano dejaba el scroll sin resetear y recién saltaba al
    // volver, moviendo la pantalla debajo del usuario en el peor momento.
    scrollMainTop() {
      var irArriba = function () {
        var m = document.querySelector("main");
        if (m) m.scrollTop = 0;
      };
      irArriba();
      setTimeout(irArriba, 0);
    },

    // ---------- sesión (A1) ----------
    // Antes acá había un usuario y una clave de superusuario hardcodeados: cualquiera que
    // abriera el front era admin y los roles del backend no protegían nada. Ahora la
    // sesión la abre una persona con sus credenciales.
    onSesionVencida(cb) { _onSesionVencida = cb; },

    hayToken() { return !!_token; },
    perfil() { return _perfil; },

    // Capacidades del rol (A5): qué acciones de escritura habilita, calculadas por el
    // backend (common/capacidades.py) y servidas en /mi/perfil/. El front las usa SOLO
    // para esconder botones; la seguridad real es el 403 del backend. Default restrictivo:
    // sin perfil o sin el objeto (token viejo, rol sin permisos), todo en false, así que
    // Empleado/Servicio no ven acciones de escritura en vez de verlas y comerse un 403.
    capacidades() { return (_perfil && _perfil.capacidades) || {}; },
    puede(clave) { return !!this.capacidades()[clave]; },

    async login(usuario, clave) {
      var r = await fetch(CONFIG.API + "/auth/token/", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ username: usuario, password: clave }),
      });
      if (!r.ok) {
        limpiarSesion();
        // 401 = credenciales; 429 = el throttle de login (5/min). Se distinguen porque el
        // usuario no puede hacer nada con "error 429", pero sí con "esperá un minuto".
        if (r.status === 429) throw new Error("Demasiados intentos. Esperá un minuto y probá de nuevo.");
        if (r.status === 401) throw new Error("Usuario o contraseña incorrectos.");
        throw new Error("No se pudo iniciar sesión (error " + r.status + ").");
      }
      var d = await r.json().catch(function () { return {}; });
      if (!d.access) throw new Error("El servidor no devolvió un token válido.");
      _token = d.access;
      guardarRefresh(d.refresh || null);
      await this.cargarPerfil();
      return _perfil;
    },

    // Reabre la sesión al recargar la página: el access murió con el JS, pero el refresh
    // sobrevivió en sessionStorage. Devuelve false si no hay nada que restaurar o si el
    // refresh ya no sirve — en ambos casos, a la pantalla de login.
    async restaurarSesion() {
      if (!_refresh) {
        try { _refresh = sessionStorage.getItem(CLAVE_SESION) || null; } catch (e) { _refresh = null; }
      }
      if (!_refresh) return false;
      if (!await refreshToken()) return false;
      try {
        await this.cargarPerfil();
      } catch (e) {
        limpiarSesion();
        return false;
      }
      return true;
    },

    async cargarPerfil() {
      _perfil = await jget("/mi/perfil/");
      return _perfil;
    },

    // Lo que va en el pie del sidebar, donde el canvas tenía "Luciana Sosa / Referente
    // RRHH · PREMOCOR" hardcodeado. Sin nombre y apellido cargados cae al username, que
    // es feo pero cierto: preferible a un nombre inventado.
    perfilVals() {
      if (!_perfil) return { nombre: "—", rol: "" };
      var nombre = ((_perfil.first_name || "") + " " + (_perfil.last_name || "")).trim();
      var roles = _perfil.roles || [];
      return {
        nombre: nombre || _perfil.username || "—",
        rol: roles.length ? roles.join(" · ") : "Sin rol asignado",
      };
    },

    logout() {
      limpiarSesion();
      // Los índices de la sesión anterior no pueden sobrevivir al cambio de usuario: el
      // que entre después ve lo que su rol permita, no lo que quedó cacheado del anterior.
      _empresaByName = {}; _empresaById = {};
      _sectorByName = {}; _sectorById = {};
      _puestoByName = {}; _puestoById = {};
      _rawEmpleados = []; _empById = {}; _empresaByRelacionId = {};
      _tipoNovByCodigo = {}; _novRawById = {}; _tipoDocByNombre = {}; _docsByEmp = {};
    },

    async init() {
      var emp = await getAllPages("/empresas/?page_size=100");
      var sec = await getAllPages("/sectores/?page_size=100");
      var pue = await getAllPages("/puestos/?page_size=100");
      emp.forEach(function (x) { _empresaByName[x.nombre] = x.id; _empresaById[x.id] = x.nombre; });
      sec.forEach(function (x) { _sectorByName[x.nombre] = x.id; _sectorById[x.id] = x.nombre; });
      pue.forEach(function (x) { _puestoByName[x.nombre.toLowerCase()] = x.id; _puestoById[x.id] = x.nombre; });
      var tipos = await getAllPages("/tipos-novedad/?page_size=100");
      tipos.forEach(function (t) { _tipoNovByCodigo[t.codigo] = t; });
      console.log("[ceibo] catálogos: " + emp.length + " empresas, " + sec.length + " sectores, " + pue.length + " puestos, " + tipos.length + " tipos de novedad");
    },

    async listEmpleados() {
      _rawEmpleados = await getAllPages("/empleados/?page_size=100");
      var mapped = _rawEmpleados.map(adapt);
      _empById = {};
      mapped.forEach(function (m) { _empById[m.id] = { name: m.name, empresa: m.empresa }; });
      // Índice relación → empresa: la ficha ya trae TODAS las relaciones (no solo la activa),
      // así que no hace falta pedir nada más para etiquetar bien las novedades viejas.
      _empresaByRelacionId = {};
      _rawEmpleados.forEach(function (e) {
        (e.relaciones || []).forEach(function (r) {
          _empresaByRelacionId[r.id] = _empresaById[r.empresa] || "—";
        });
      });
      console.log("[ceibo] backend conectado: " + mapped.length + " empleados");
      return mapped;
    },

    // Métricas del panel general. Devuelve el dict crudo del backend (o null si el
    // rol no tiene panel / falla la red); el componente lo pasa por dashboardVals.
    async loadDashboard() {
      try { return await jget("/dashboard/metricas/"); }
      catch (e) { console.warn("[ceibo] dashboard no disponible", e); return null; }
    },
    // Traduce la respuesta del backend a las vars del diseño (metrics, rankFaltas,
    // rotación). `mockMetrics` aporta solo los íconos SVG del canvas.
    dashboardVals(d, rotState, mockMetrics) {
      var out = { metrics: dashMetrics(d, mockMetrics), rankFaltas: dashRank(d) };
      return Object.assign(out, dashRotacion(d, rotState || "m"));
    },

    // Vencimientos de toda la dotación (documentos + contratos). Como el dashboard:
    // devuelve el dict crudo, o null si el rol no ve la dotación / falla la red.
    async loadVencimientos() {
      try { return await jget("/alertas/vencimientos/"); }
      catch (e) { console.warn("[ceibo] vencimientos no disponibles", e); return null; }
    },

    // Alertas del día (tarjeta del panel): vencimientos + certificados + cumpleaños.
    async loadAlertasDia() {
      try { return await jget("/alertas/del-dia/"); }
      catch (e) { console.warn("[ceibo] alertas del día no disponibles", e); return null; }
    },
    // El backend manda `estado` (bad/warn/info), no colores: el semáforo lo pinta el diseño.
    alertasDiaVals(d, ui) {
      return {
        alertasDia: (d.items || []).map(function (i) {
          return { title: i.title, text: i.text, dot: ui.dotDe(i.estado) };
        }),
        hoyLabel: d.fecha,
      };
    },

    // Parametría de alertas: con cuántos días de anticipación avisa cada cosa.
    async loadConfigVenc() {
      try { return (await jget("/config/vencimientos/")).filas; }
      catch (e) { console.warn("[ceibo] config de vencimientos no disponible", e); return null; }
    },
    async guardarDiasAviso(clave, dias) {
      return await jsend("PATCH", "/config/vencimientos/", { clave: clave, dias: dias });
    },
    // Traduce la respuesta a las vars del diseño (vencGroups, vencResumen).
    // `ui` son los helpers de estilo del componente: el semáforo lo define el canvas, acá
    // solo se lo llama. `mockGroups` aporta el ícono SVG, igual que mockMetrics en el panel.
    vencimientosVals(d, ui, mockGroups) {
      var icono = (mockGroups && mockGroups[0] && mockGroups[0].icon) || "";
      var grupos = (d.grupos || []).map(function (g) {
        var items = g.items || [];
        var n = { ok: 0, warn: 0, bad: 0 };
        items.forEach(function (i) { n[i.estado] = (n[i.estado] || 0) + 1; });
        return {
          tipo: g.tipo,
          icon: icono,
          items: items.map(function (i) {
            return {
              emp: nombreNatural(i.empleado),
              empresa: i.empresa,
              // Sin fecha cargada: el guion es el mismo que usa el canvas en su mock.
              fecha: i.fecha ? fmtISOtoDMY(i.fecha) : "—",
              dot: ui.dot(ui.semColor(i.estado)),
              badge: ui.badge(i.estado),
              label: ui.semLabel(i.estado),
            };
          }),
          summary: n.ok + " al día · " + n.warn + " por vencer · " + n.bad + " vencidos",
        };
      });
      var r = d.resumen || {};
      return {
        vencGroups: grupos,
        // El resumen viene contado del backend: es la dotación entera, no solo lo que
        // se está mostrando.
        vencResumen: [
          { n: r.vencidos || 0, label: "Vencidos", dotBig: ui.dot("var(--bad)") },
          { n: r.por_vencer || 0, label: "Próximos a vencer", dotBig: ui.dot("var(--warn)") },
          { n: r.al_dia || 0, label: "Al día", dotBig: ui.dot("var(--ok)") },
        ],
      };
    },

    // Destinatarios y canales de aviso. El canvas los resuelve con estado local
    // (toggleRole/toggleCanal) y no hay dónde guardarlos: en `gestion_rrhh` no existe
    // modelo ni endpoint de notificaciones. Los chips y switches cambiaban de color, se
    // perdían al recargar y nadie lo decía, así que el usuario creía haber configurado
    // avisos que nunca se iban a enviar. Hasta que exista el módulo se muestran apagados
    // y el click explica por qué, en vez de simular una configuración que no persiste.
    notifVals(v) {
      var apagar = function (s) { return (s || "") + ";opacity:.45;cursor:not-allowed"; };
      var avisar = function () {
        showToast("Los destinatarios y canales todavía no se pueden configurar: falta el " +
          "módulo de notificaciones.", "error");
      };
      return {
        notifSubtitle: "A quién y por dónde se enviarán los avisos de vencimiento. " +
          "Todavía no se puede configurar: los valores son de referencia y no se guardan.",
        roles: (v.roles || []).map(function (r) {
          return { label: r.label, chip: apagar(r.chip), toggle: avisar };
        }),
        canales: (v.canales || []).map(function (c) {
          // `on` se conserva: es lo que alimenta el aria-checked del role="switch". Sin él
          // el switch se anuncia sin estado y un lector de pantalla no sabe si está activo.
          return {
            label: c.label, hint: c.hint, on: String(!!c.on),
            track: apagar(c.track), knob: c.knob, toggle: avisar,
          };
        }),
      };
    },

    // Novedades con cadenas expandidas: se agrupan las prórrogas bajo su madre
    // (novedad_origen) para tener la cadena completa sin N+1.
    async listNovedades() {
      var raw = await getAllPages("/novedades/?expandir_cadenas=true&page_size=100");
      _novRawById = {};
      raw.forEach(function (n) { _novRawById[n.id] = n; });
      var madres = raw.filter(function (n) { return !n.novedad_origen; });
      var rows = madres.map(function (m) {
        var out = adaptNov(m);
        var pros = raw.filter(function (n) { return n.novedad_origen === m.id; })
          .sort(function (a, b) { return a.fecha_desde < b.fecha_desde ? -1 : 1; });
        out.prorrogas = pros.map(function (p) {
          return {
            id: p.id, esProrroga: true,
            desde: fmtISOtoDMY(p.fecha_desde), hasta: fmtISOtoDMY(p.fecha_hasta),
            motivo: p.motivo || "", estado: p.estado_display,
            cert: !!p.certificado_recibido_en,
          };
        });
        if (pros.length) {
          out.madreDesde = fmtISOtoDMY(m.fecha_desde);
          out.madreHasta = fmtISOtoDMY(m.fecha_hasta);
          out.madreMotivo = m.motivo || m.tipo_novedad_nombre;
          // La grilla muestra la vigencia EFECTIVA: madre.desde → hasta de la última
          // prórroga no anulada (antes mostraba solo el rango original de la madre).
          var vigHasta = m.fecha_hasta;
          pros.forEach(function (p) { if (p.estado_display !== "Anulada") vigHasta = p.fecha_hasta; });
          out.fecha = fmtRango(m.fecha_desde, vigHasta);
        }
        return out;
      });
      console.log("[ceibo] novedades: " + rows.length + " cadenas");
      return rows;
    },

    // Prepara el alta de novedad: empleado como autocomplete (input + datalist) validado
    // contra la base, fecha por defecto = hoy, y fin estimada que se recalcula con los días.
    populateNovForm() {
      if (!document.querySelector('[data-modal="altanov"]')) return;
      var f = readModalForm('[data-modal="altanov"]');
      // Empleado: convertir el <select> en caja de texto con autocompletado.
      var empEl = f["empleado"];
      if (empEl && empEl.tagName === "SELECT") {
        var input = document.createElement("input");
        input.setAttribute("list", "ceibo-emp-list");
        input.setAttribute("placeholder", "Escribí el nombre del empleado…");
        input.setAttribute("autocomplete", "off");
        input.style.cssText = empEl.style.cssText;  // hereda el look del diseño
        var dl = document.createElement("datalist");
        dl.id = "ceibo-emp-list";
        // Solo empleados ACTIVOS: no se cargan novedades nuevas sobre egresados (el backend
        // también lo rechaza). Las novedades históricas de un egresado se conservan.
        dl.innerHTML = _rawEmpleados.filter(function (e) { return e.activo; }).map(function (e) {
          return '<option value="' + (e.nombre + " " + e.apellido).trim() + '"></option>';
        }).join("");
        empEl.parentNode.replaceChild(input, empEl);
        input.parentNode.appendChild(dl);
      }
      prepararInputCertificado(f);
      // Estado: solo los que el backend sabe aplicar (ver podarEstadosNov).
      podarEstadosNov(f["estado"]);
      // Fecha de la novedad: por defecto hoy (si está vacía).
      var fecha = f["fecha"];
      if (fecha && !fecha.value) fecha.value = fmtISOtoDMY(todayISO());
      // Fin estimada = fecha + días: recalcular al tipear días o cambiar la fecha.
      ["dias", "fecha"].forEach(function (k) {
        var el = f[k];
        if (el && !el._ceiboWired) {
          el._ceiboWired = true;
          el.addEventListener("input", recomputeFinEstimada);
        }
      });
    },

    // Alta de novedad: lee el modal por etiqueta, POST /novedades/ y, si se eligió un
    // estado con transición (Aprobada/Rechazada/Anulada), la aplica en cadena.
    async submitNov(editNovId) {
      var f = readModalForm('[data-modal="altanov"]');
      var g = function (k) { var el = f[k]; return el ? el.value.trim() : ""; };
      // "Archivo certificado" venía del diseño sin cablear: el archivo se elegía y se
      // perdía en silencio. Se sube DESPUÉS de que la novedad exista, porque el endpoint
      // de respaldos cuelga de su id (/novedades/{id}/adjuntos/).
      var certEl = f["archivo certificado"];
      var cert = certEl && certEl.files && certEl.files[0];
      var codigo = TIPONOV[g("tipo")] || "";
      var tipo = _tipoNovByCodigo[codigo];
      if (!tipo) throw new Error("Tipo de novedad inválido");
      var desde = parseFecha(g("fecha"));
      if (!desde) throw new Error("Fecha obligatoria (dd/mm/aaaa)");
      var payload = {
        tipo_novedad: tipo.id, fecha_desde: desde,
        motivo: g("motivo"), observaciones: g("observaciones"),
      };
      // Al editar una prórroga, prefillNovForm renombró "Días" → "Fecha de fin": se corrige
      // por su fecha_hasta directa (no por días, ni tocando praxis; ver prefillNovForm).
      var editRaw = editNovId ? _novRawById[editNovId] : null;
      var esProrrogaEdit = !!(editRaw && editRaw.novedad_origen);
      if (esProrrogaEdit) {
        var fin = parseFecha(g("fecha de fin"));
        if (!fin) throw new Error("Fecha de fin obligatoria (dd/mm/aaaa)");
        if (fin < desde) throw new Error("La fecha de fin no puede ser anterior al inicio.");
        payload.fecha_hasta = fin;
      } else {
        // Días → fecha_hasta (el PATCH de edición no acepta 'dias', así que mandamos el rango).
        var dias = g("dias"); if (dias) payload.fecha_hasta = addDaysISO(desde, Number(dias) - 1);
      }
      var aviso = parseFecha(g("fecha aviso del empleado")); if (aviso) payload.fecha_aviso_empleado = aviso;
      var clasif = CLASIF[g("clasificacion")]; if (clasif) payload.clasificacion = clasif;
      if (codigo === "HORAS_EXTRA") {
        var h = g("cantidad de horas");
        if (!h) throw new Error("Cantidad de horas obligatoria");
        payload.cantidad_horas = h;
      } else if (!esProrrogaEdit) {
        // El bloque de praxis se muestra cuando el toggle está activo: si sus inputs existen,
        // la novedad requiere praxis y se envían las fechas cargadas.
        var praxisFields = ["fecha turno praxis", "fecha fin estimada", "fecha reintegro", "fecha certificado recibido"];
        var apiKeys = ["fecha_turno_praxis", "fecha_fin_estimada", "fecha_reintegro", "certificado_recibido_en"];
        if (f["fecha turno praxis"]) payload.requiere_praxis = true;
        praxisFields.forEach(function (lbl, i) { var v = parseFecha(g(lbl)); if (v) payload[apiKeys[i]] = v; });
      }
      if (editNovId) {
        await jsend("PATCH", "/novedades/" + editNovId + "/", payload);  // empleado/estado no se tocan
        if (cert) await adjuntarCertificado(editNovId, cert, "Los cambios se guardaron");
        showToast("Novedad actualizada", "ok");
        return;
      }
      var empEl = f["empleado"];
      var empId = empEl && empEl.tagName === "SELECT" ? empEl.value : empIdByName(g("empleado"));
      if (!empId) throw new Error("Empleado inválido: elegí un nombre de la lista de registrados");
      payload.empleado = Number(empId);
      // El estado se valida ANTES de crear: podarEstadosNov ya saca los no soportados del
      // <select>, pero si el diseño cambia y vuelve a ofrecerlos, esto corta acá en vez de
      // dejar la novedad en un estado distinto del elegido.
      var estadoSel = g("estado");
      var accion = ESTADONOV[estadoSel];
      if (estadoSel && estadoSel !== "Registrada" && !accion) {
        throw new Error('El estado "' + estadoSel + '" todavía no se puede aplicar. ' +
          "Registrá la novedad y cambiale el estado desde el detalle.");
      }
      var nov = await jsend("POST", "/novedades/", payload);
      if (accion) {
        // La novedad YA existe: si la transición falla hay que decirlo con todas las letras.
        // Un "error" a secas invita a reintentar el alta, y eso duplicaría el registro.
        try {
          await jsend("POST", "/novedades/" + nov.id + "/" + accion + "/", {});
        } catch (e) {
          throw new Error('La novedad se registró, pero no se pudo pasar a "' + estadoSel +
            '": ' + e.message + ". No la cargues de nuevo: cambiale el estado desde el detalle.");
        }
      }
      if (cert) await adjuntarCertificado(nov.id, cert, "La novedad se registró");
      showToast("Novedad registrada", "ok");
    },

    // Transición de estado por endpoint dedicado (aprobar/rechazar/anular).
    async transicionNov(id, accion) {
      if (!id) throw new Error("no hay novedad seleccionada");
      await jsend("POST", "/novedades/" + id + "/" + accion + "/", {});
      var txt = { aprobar: "aprobada", rechazar: "rechazada", anular: "anulada" }[accion] || accion;
      showToast("Novedad " + txt, "ok");
    },

    // Etiqueta del <select> Tipo para precargar en edición (desde el código real del backend).
    novFormTipoFor(id) {
      var n = _novRawById[id];
      return n ? (TIPONOV_REV[n.tipo_novedad_codigo] || "Falta") : "Falta";
    },

    // Precarga el form en modo edición desde la novedad real (DOM). El empleado no se edita:
    // se muestra su nombre en un campo deshabilitado.
    prefillNovForm(id) {
      var n = _novRawById[id];
      if (!n) return;
      var f = readModalForm('[data-modal="altanov"]');
      var set = function (k, iso) { if (f[k] != null) f[k].value = iso ? fmtISOtoDMY(iso) : ""; };
      var empEl = f["empleado"];
      if (empEl) {
        var ro = document.createElement("input");
        ro.value = (_empById[n.empleado] && _empById[n.empleado].name) || nombreNatural(n.empleado_nombre) || "";
        ro.disabled = true;
        ro.style.cssText = empEl.style.cssText + ";opacity:.65;cursor:not-allowed";
        empEl.parentNode.replaceChild(ro, empEl);
      }
      // El PATCH de novedad no toca el estado (lo mueven aprobar/rechazar/anular desde el
      // detalle). Editable, prometía un cambio que nunca se mandaba. Se muestra el estado
      // real —no el que dejó el canvas— y se bloquea.
      if (f["estado"]) f["estado"].value = n.estado_display || f["estado"].value;
      lockCampo(f["estado"], ESTADO_NOV_LOCK_MSG);
      set("fecha", n.fecha_desde);
      if (f["motivo"]) f["motivo"].value = n.motivo || "";
      if (f["observaciones"]) f["observaciones"].value = n.observaciones || "";
      if (f["clasificacion"]) f["clasificacion"].value = CLASIF_REV[n.clasificacion] || "";
      if (n.novedad_origen) {
        // Editar una PRÓRROGA: su inicio es contiguo a la cadena (no se edita) y su
        // corrección natural es la FECHA DE FIN (fecha_hasta), no "Días" ni "Fecha fin
        // estimada" (esta última es una anotación de praxis, no la vigencia). Se reusa
        // el input de "Días" in situ, renombrando la etiqueta —solo en este modo.
        var fIni = f["fecha"];
        if (fIni) { fIni.disabled = true; fIni.style.cssText += ";opacity:.65;cursor:not-allowed"; }
        var fDias = f["dias"];
        if (fDias) {
          var lblDias = labelDivOf(fDias);
          if (lblDias) lblDias.textContent = "Fecha de fin";
          fDias.placeholder = "dd/mm/aaaa";
          fDias.setAttribute("maxlength", "10");
          fDias.value = fmtISOtoDMY(n.fecha_hasta);
        }
      } else if (f["dias"] && n.fecha_hasta) {
        f["dias"].value = String(diasEntreISO(n.fecha_desde, n.fecha_hasta));
      }
      if (f["cantidad de horas"] && n.cantidad_horas != null) f["cantidad de horas"].value = String(Number(n.cantidad_horas));
      set("fecha aviso del empleado", n.fecha_aviso_empleado);
      set("fecha turno praxis", n.fecha_turno_praxis);
      set("fecha fin estimada", n.fecha_fin_estimada);
      set("fecha reintegro", n.fecha_reintegro);
      set("fecha certificado recibido", n.certificado_recibido_en);
      prepararInputCertificado(f);
    },

    // Prórroga: lee el modal, POST /novedades/{id}/prorrogar/.
    async submitProrroga(detNovId) {
      if (!detNovId) throw new Error("no hay novedad seleccionada");
      var f = readModalForm('[data-modal="prorroga"]');
      var g = function (k) { var el = f[k]; return el ? el.value.trim() : ""; };
      var hasta = parseFecha(g("nueva fecha de fin"));
      if (!hasta) throw new Error("Nueva fecha de fin obligatoria (dd/mm/aaaa)");
      var payload = { fecha_hasta_nueva: hasta, motivo: g("motivo de la prórroga") };
      var cert = parseFecha(g("certificado recibido — fecha")); if (cert) payload.certificado_recibido_en = cert;
      await jsend("POST", "/novedades/" + detNovId + "/prorrogar/", payload);
      showToast("Prórroga registrada", "ok");
    },

    // Alta (editId=null) o edición (editId=id). Lee el form del DOM por etiqueta.
    // `exento` llega aparte: "Exento de marcación" es un toggle del diseño (un <div>, no un
    // input), así que readAltaForm no lo ve. Sin este parámetro el campo se mostraba, se
    // podía tocar y nunca se mandaba —y al editar volvía a false en cada guardado—.
    async submitAlta(editId, exento) {
      var f = readAltaForm();
      var g = function (k) { var el = f[k]; return el ? el.value.trim() : ""; };
      var nm = splitName(g("nombre y apellido"));
      var payload = {
        nombre: nm.nombre, apellido: nm.apellido,
        cuil: g("cuil") || null,
        fecha_nacimiento: parseFecha(g("fecha de nacimiento")),
        educacion: EDU[g("educacion")] || "",
        direccion: g("domicilio"),
        telefono: g("telefono"),
        email: g("email"),
        contacto_emergencia: g("contacto de emergencia"),
        id_huella: g("id de huella") || null,
        exento_marcacion: !!exento,
        obra_social: g("obra social"),
        art: g("art"),
        observaciones: g("observaciones"),
      };
      if (editId) {
        await jsend("PATCH", "/empleados/" + editId + "/", payload);   // solo datos de la persona
        showToast("Empleado actualizado", "ok");
        return;
      }
      // Alta completa: empleado + relación ACTIVA.
      if (!nm.nombre || !g("dni")) throw new Error("Nombre y DNI son obligatorios");
      var empresaId = _empresaByName[g("empresa")];
      if (!empresaId) throw new Error("Seleccioná la empresa");   // define en qué empresa corre la jornada
      var fechaIng = parseFecha(g("fecha de ingreso"));
      if (!fechaIng) throw new Error("Fecha de ingreso obligatoria (dd/mm/aaaa)");
      var dni = g("dni").replace(/\./g, "");
      var puestoId = await getOrCreatePuesto(g("puesto"));
      var relacion = {
        empresa: empresaId, sector: _sectorByName[g("sector")],
        puesto: puestoId, fecha_ingreso: fechaIng, jornada_legal: JORNADA[g("jornada legal")] || "",
      };
      // ¿Ya existe una persona con ese DNI? Entonces no es un alta nueva: es un REINGRESO.
      // El DNI es único a nivel grupo; se valida contra la base para no chocar con el
      // índice único y, sobre todo, para no duplicar la persona.
      var existente = await findEmpleadoByDni(dni);
      if (existente) {
        if (existente.activo) {
          throw new Error(
            "Ya existe un empleado activo con DNI " + dni + " (" +
            (existente.nombre + " " + existente.apellido).trim() +
            "). No se puede dar de alta otra vez."
          );
        }
        // Persona egresada: se reincorpora con una nueva relación ACTIVA en la empresa
        // elegida. No se pisan sus datos personales (para eso está la edición de ficha).
        await jsend("POST", "/empleados/" + existente.id + "/relaciones/", relacion);
        showToast("Reingreso registrado (el DNI ya existía)", "ok");
        return;
      }
      payload.dni = dni;
      payload.relacion = relacion;   // el legajo lo asigna el backend (no se manda)
      await jsend("POST", "/empleados/", payload);
      showToast("Empleado dado de alta", "ok");
    },

    // Prefill del form cuando se abre en modo edición.
    prefillAlta(emp) {
      if (!emp) return;
      var f = readAltaForm();
      var set = function (k, v) { if (f[k] != null && v != null) f[k].value = v; };
      set("nombre y apellido", emp.name);
      set("dni", emp.dni);
      set("cuil", emp.cuil);
      set("fecha de nacimiento", emp.nac);           // el input formatea dd/mm/aaaa
      set("domicilio", emp.domicilio);
      set("telefono", emp.tel);
      set("email", emp.email);
      set("contacto de emergencia", emp.contacto_emergencia);
      set("id de huella", emp.id_huella);
      set("obra social", emp.obra_social);
      set("art", emp.art);
      set("observaciones", emp.observaciones);
      set("fecha de ingreso", emp.ingreso);
      if (f["educacion"] && emp.educacion) f["educacion"].value = EDU_REV[emp.educacion] || f["educacion"].value;
      if (f["jornada legal"] && emp.jornada_legal) f["jornada legal"].value = JORNADA_REV[emp.jornada_legal] || f["jornada legal"].value;
      if (f["empresa"] && emp.empresa !== "—") f["empresa"].value = emp.empresa;
      if (f["sector"] && emp.sector !== "—") f["sector"].value = emp.sector;
      if (f["puesto"]) f["puesto"].value = emp.puesto === "—" ? "" : emp.puesto;
      // El PATCH de edición solo toca datos de la persona: se bloquea todo lo demás para
      // no aceptar cambios que se descartan en silencio (ver CAMPOS_RELACION arriba).
      lockCampo(f["empresa"], EMPRESA_LOCK_MSG);
      lockCampo(f["dni"], DNI_LOCK_MSG);
      CAMPOS_RELACION.forEach(function (k) { lockCampo(f[k], RELACION_LOCK_MSG); });
      lockCampo(f["estado"], ESTADO_LOCK_MSG);
      notaEdicion(f);
    },

    // Prepara el modal en modo ALTA: habilita empresa y fuerza una elección consciente
    // (opción vacía "Seleccionar empresa…" por defecto), para que la jornada quede bien
    // encuadrada en la empresa correcta y no caiga en la primera por descuido.
    prepareAlta() {
      var f = readAltaForm();
      quitarNotaEdicion();          // el modal es el mismo que el de edición
      unlockEmpresa(f["empresa"]);
      unlockCampo(f["dni"]);
      CAMPOS_RELACION.forEach(function (k) { unlockCampo(f[k]); });
      // El estado se bloquea también en el alta: un alta nace ACTIVA (la relación se crea
      // así) y el <select> nunca se leyó, con lo cual elegir "Inactivo" tampoco hacía nada.
      lockCampo(f["estado"], ESTADO_LOCK_MSG);
    },

    // Baja lógica: motivo del modal de baja, finaliza la relación ACTIVA (fecha = hoy).
    async darDeBaja(emp) {
      if (!emp || !emp._relacionActivaId) throw new Error("el empleado no tiene relación activa");
      var m = document.querySelector('[data-modal="baja"]');
      var sel = m ? m.querySelector("select") : null;
      var motivo = MOTIVO[sel ? sel.value : "Renuncia"] || "RENUNCIA";
      // Fecha de egreso: input de fecha del modal (placeholder empieza "dd/mm/aaaa"); vacío = hoy.
      var fEl = m ? m.querySelector('input[placeholder^="dd/mm/aaaa"]') : null;
      var fecha = parseFecha(fEl ? fEl.value : "") || todayISO();
      await jsend("POST", "/empleados/" + emp.id + "/relaciones/" + emp._relacionActivaId + "/finalizar/", {
        fecha_egreso: fecha, motivo_egreso: motivo,
      });
      showToast("Baja registrada", "ok");
    },

    // Reingreso: nueva relación ACTIVA (misma empresa de la última relación).
    // La fecha de reincorporación sale del modal (placeholder empieza "dd/mm/aaaa"); vacío = hoy.
    // Arrastra sector/puesto/jornada/contrato de la última relación: el modal no los
    // pregunta, y sin esto la relación nueva queda pelada (la ficha mostraría "—").
    async reingreso(emp) {
      if (!emp) throw new Error("empleado no encontrado");
      if (!emp._empresaId) throw new Error("no hay empresa de referencia para el reingreso");
      var m = document.querySelector('[data-modal="reingreso"]');
      var fEl = m ? m.querySelector('input[placeholder^="dd/mm/aaaa"]') : null;
      var fecha = parseFecha(fEl ? fEl.value : "") || todayISO();
      var nueva = { empresa: emp._empresaId, fecha_ingreso: fecha };
      if (emp._sectorId) nueva.sector = emp._sectorId;
      if (emp._puestoId) nueva.puesto = emp._puestoId;
      if (emp._jornadaLegal) nueva.jornada_legal = emp._jornadaLegal;
      if (emp._tipoContrato) nueva.tipo_contrato = emp._tipoContrato;
      await jsend("POST", "/empleados/" + emp.id + "/relaciones/", nueva);
      showToast("Reingreso registrado", "ok");
    },

    // Documentos de un empleado (lectura) → shape del diseño.
    async loadDocs(id) {
      var docs = await jget("/empleados/" + id + "/documentos/");
      _docsByEmp[id] = docs || [];
      return (docs || []).map(function (d) {
        return {
          id: d.id,
          tipo: d.tipo_documento_nombre || ("Documento #" + d.tipo_documento),
          fecha: d.fecha_vencimiento ? "Vence " + fmtISOtoDMY(d.fecha_vencimiento) : "Sin vencimiento",
          estado: docEstado(d.fecha_vencimiento),
          tieneArchivo: !!d.tiene_archivo,
        };
      });
    },

    // Catálogo de tipos (reemplaza los 4 hardcodeados del canvas: RRHH puede agregar más).
    async listTiposDoc() {
      var rows = await getAllPages("/tipos-documento/?activo=true");
      rows.forEach(function (t) { _tipoDocByNombre[t.nombre] = t; });
      return rows.map(function (t) { return { nombre: t.nombre }; });
    },

    // Prepara el modal. En alta: deja elegido el primer tipo que el empleado NO tenga
    // (hay uno vigente por tipo; ofrecer uno repetido garantiza un 400 al guardar).
    // En edición: precarga los valores y bloquea el tipo (cambiarlo sería otro documento).
    prepareDoc(empId, docId) {
      var m = document.querySelector('[data-modal="doc"]');
      if (!m) return;
      var f = function (k) { return m.querySelector('[data-doc="' + k + '"]'); };
      var cargados = (_docsByEmp[empId] || []).map(function (d) { return d.tipo_documento_nombre; });
      var sel = f("tipo");
      if (sel && !docId) {
        var libre = Array.prototype.find.call(sel.options, function (o) {
          return cargados.indexOf(o.value) < 0;
        });
        if (libre) sel.value = libre.value;
      }
      // El cartel del archivo elegido lo maneja el diseño ({{ docArchivoLabel }}): es
      // estado de UI, no cableado. Acá solo se llenan los campos que salen del backend.
      if (!docId) {
        ["numero", "vencimiento", "observaciones"].forEach(function (k) { if (f(k)) f(k).value = ""; });
        if (f("archivo")) f("archivo").value = "";
        return;
      }
      var doc = (_docsByEmp[empId] || []).find(function (d) { return d.id === docId; });
      if (!doc) return;
      if (sel) sel.value = doc.tipo_documento_nombre;
      if (f("numero")) f("numero").value = doc.numero || "";
      if (f("vencimiento")) f("vencimiento").value = fmtISOtoDMY(doc.fecha_vencimiento);
      if (f("observaciones")) f("observaciones").value = doc.observaciones || "";
      if (f("archivo")) f("archivo").value = "";
    },

    // Alta/edición. Va como multipart (no JSON) porque puede llevar el archivo.
    async submitDoc(empId, docId) {
      var m = document.querySelector('[data-modal="doc"]');
      if (!m) throw new Error("modal de documento no encontrado");
      var f = function (k) { return m.querySelector('[data-doc="' + k + '"]'); };
      var g = function (k) { return f(k) ? f(k).value.trim() : ""; };

      var fd = new FormData();
      if (!docId) {
        var tipo = _tipoDocByNombre[g("tipo")];
        if (!tipo) throw new Error("Elegí un tipo de documento.");
        fd.append("tipo_documento", tipo.id);   // en edición el tipo no se manda: no se edita
      }
      fd.append("numero", g("numero"));
      fd.append("observaciones", g("observaciones"));
      var venc = parseFecha(g("vencimiento"));
      if (venc) fd.append("fecha_vencimiento", venc);
      var input = f("archivo");
      var file = input && input.files && input.files[0];
      // Sin archivo nuevo, el campo NO se manda: mandarlo vacío borraría el respaldo actual.
      if (file) fd.append("archivo", file);

      var path = docId
        ? "/empleados/" + empId + "/documentos/" + docId + "/"
        : "/empleados/" + empId + "/documentos/";
      // Sin content-type a mano: el browser arma el boundary del multipart él solo.
      var r = await authedFetch(CONFIG.API + path, { method: docId ? "PATCH" : "POST", body: fd });
      var data = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        var msg = (data.campos && Object.keys(data.campos).length)
          ? flattenErrs(data.campos).join(" · ")
          : (data.detalle || ("Error " + r.status));
        throw new Error(msg);
      }
      showToast(docId ? "Documento actualizado" : "Documento cargado", "ok");
      return data;
    },

    // Descarga del respaldo. No alcanza un <a href>: el endpoint exige el header
    // Authorization y un link plano no lo manda (por eso media/ no es público).
    async descargarDoc(empId, docId) {
      var r = await authedFetch(CONFIG.API + "/empleados/" + empId + "/documentos/" + docId + "/archivo/", {});
      if (!r.ok) throw new Error(r.status === 404 ? "El documento no tiene respaldo cargado." : "Error " + r.status);
      var blob = await r.blob();
      // El nombre legible lo arma el backend en Content-Disposition; se respeta.
      var cd = r.headers.get("content-disposition") || "";
      var m = /filename="([^"]+)"/.exec(cd);
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = m ? m[1] : "documento";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);   // sin esto el blob queda retenido en memoria
    },

    async quitarDoc(empId, docId) {
      var r = await authedFetch(CONFIG.API + "/empleados/" + empId + "/documentos/" + docId + "/", { method: "DELETE" });
      if (!r.ok) throw new Error("No se pudo quitar el documento (" + r.status + ")");
      showToast("Documento quitado", "ok");
    },

    // ---------- Adjuntos de novedad (la bitácora del hecho) ----------
    // El id que ve el front es el de la novedad abierta: si es una prórroga, sus respaldos
    // son de ESE eslabón, no de la madre. Por eso no se redirige a la madre como en
    // `prorrogar`: el certificado de la extensión pertenece a la extensión.
    async loadAdjuntos(novId) {
      var rows = await jget("/novedades/" + novId + "/adjuntos/");
      return (rows || []).map(function (a) {
        var quien = a.subido_por || "sistema";
        return {
          id: a.id,
          nombre: a.nombre_original,
          // La descripción es opcional; si está, dice más que la fecha sola.
          meta: (a.descripcion ? a.descripcion + " · " : "") + quien + " · " + fmtISOtoDMY((a.creado_en || "").slice(0, 10)),
        };
      });
    },

    async subirAdjunto(novId, file) {
      var fd = new FormData();
      fd.append("archivo", file);
      // Sin content-type a mano: el browser arma el boundary del multipart él solo.
      var r = await authedFetch(CONFIG.API + "/novedades/" + novId + "/adjuntos/", {
        method: "POST", body: fd,
      });
      var data = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        var msg = (data.campos && Object.keys(data.campos).length)
          ? flattenErrs(data.campos).join(" · ")
          : (data.detalle || ("Error " + r.status));
        throw new Error(msg);
      }
      showToast("Respaldo adjuntado", "ok");
      return data;
    },

    async descargarAdjunto(novId, adjId) {
      var r = await authedFetch(CONFIG.API + "/novedades/" + novId + "/adjuntos/" + adjId + "/archivo/", {});
      if (!r.ok) throw new Error("No se pudo descargar el respaldo (" + r.status + ")");
      var blob = await r.blob();
      var cd = r.headers.get("content-disposition") || "";
      var m = /filename="([^"]+)"/.exec(cd);
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = m ? m[1] : "adjunto";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);   // sin esto el blob queda retenido en memoria
    },

    async quitarAdjunto(novId, adjId) {
      var r = await authedFetch(CONFIG.API + "/novedades/" + novId + "/adjuntos/" + adjId + "/", { method: "DELETE" });
      if (!r.ok) throw new Error("No se pudo quitar el respaldo (" + r.status + ")");
      showToast("Respaldo quitado", "ok");
    },
  };
})();
