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
    // Producción sirve frontend y Django bajo el mismo origen. El desarrollo local debe
    // usar el mismo proxy; no se codifican host/puerto de una máquina concreta acá.
    API: "/api/v1",
    TIMEOUT_MS: 20000,
  };

  // Sesión Django. La credencial vive exclusivamente en la cookie HttpOnly del servidor:
  // JavaScript no recibe ni persiste credenciales de API. El perfil sí queda en memoria
  // para renderizar capacidades; al recargar se reconstruye desde /mi/perfil/.
  var _perfil = null;
  // Lo llama el cableado para volver a la pantalla de login cuando el servidor responde 401.
  var _onSesionVencida = null;
  var _sesionVencidaNotificada = false;

  function limpiarSesion() {
    _perfil = null;
  }
  var _empresaByName = {}, _empresaById = {};
  var _sectorByName = {}, _sectorById = {};
  // Un nombre de puesto solo es único DENTRO de su sector. El índice compuesto evita que
  // "Encargado" de Taller termine resolviendo al "Encargado" de Administración.
  var _puestoBySectorNombre = {}, _puestoById = {};
  // Catálogo con el flag `activa/activo`: los dropdowns de alta ofrecen SOLO los activos (una
  // empresa/sector dado de baja no se puede elegir para una relación nueva), pero el ABM de
  // Configuración lista todos para poder reactivarlos. Los mapas de arriba resuelven nombre↔id.
  var _empresasCat = [];          // [{ id, nombre, activa }]
  var _sectoresCat = [];          // [{ id, nombre, activo }]
  var _puestosCat = [];           // [{ id, nombre, sector, activo }]
  var _supervisoresCat = [];      // [{ id, username, nombre_completo }]
  var _rawEmpleados = [];
  var _empById = {};              // id → { name, empresa } (para adaptar novedades)
  // relación laboral → nombre de empresa. La novedad guarda de QUÉ relación es, así que la
  // etiqueta sale de ahí y no de la relación activa del empleado (ver adaptNov).
  var _empresaByRelacionId = {};
  var _tipoNovByCodigo = {};      // codigo → tipo de novedad (con flags)
  var _novRawById = {};           // id → novedad cruda del backend (para precargar edición)
  var _tipoDocByNombre = {};      // nombre → tipo de documento (el select del modal da el nombre)
  var _docsByEmp = {};            // empleado id → documentos crudos (para precargar la edición)
  var _fotoUrls = {};             // empleado id → objectURL de su foto (blob cacheado, se revoca)

  // El blob de la foto se descarga por el endpoint autenticado y se envuelve en un objectURL.
  // Así se tratan 401/403 y se lo puede revocar al reemplazar o cerrar sesión.
  function revocarFoto(empId) {
    if (_fotoUrls[empId]) { URL.revokeObjectURL(_fotoUrls[empId]); delete _fotoUrls[empId]; }
  }
  function revocarTodasLasFotos() {
    Object.keys(_fotoUrls).forEach(revocarFoto);
  }

  // ---------- HTTP ----------
  var _apiBase = new URL(CONFIG.API.replace(/\/+$/, "") + "/", window.location.origin);
  function apiUrl(path) {
    var raw = String(path || "");
    var url = /^https?:\/\//i.test(raw)
      ? new URL(raw)
      : new URL(raw.replace(/^\/+/, ""), _apiBase);
    // Una cookie de sesión nunca debe acompañar un `next` o una ruta que salga del API del
    // mismo origen. DRF suele devolver `next` absoluto, por eso no alcanza con concatenar.
    if (url.origin !== window.location.origin ||
        url.pathname.indexOf(_apiBase.pathname) !== 0) {
      throw new Error("La API devolvió una URL de paginación no permitida.");
    }
    return url.href;
  }
  async function fetchConTimeout(url, opts) {
    opts = Object.assign({}, opts || {});
    if (typeof AbortController === "undefined") return fetch(url, opts);
    var externo = opts.signal || null;
    var ctrl = new AbortController();
    var vencio = false;
    var propagarAbort = function () { ctrl.abort(); };
    if (externo) {
      if (externo.aborted) ctrl.abort();
      else externo.addEventListener("abort", propagarAbort, { once: true });
    }
    opts.signal = ctrl.signal;
    var timer = setTimeout(function () {
      vencio = true;
      ctrl.abort();
    }, CONFIG.TIMEOUT_MS);
    try {
      return await fetch(url, opts);
    } catch (e) {
      if (vencio) {
        var timeout = new Error("La solicitud tardó demasiado. Revisá la conexión e intentá de nuevo.");
        timeout.codigo = "TIMEOUT";
        throw timeout;
      }
      throw e;
    } finally {
      clearTimeout(timer);
      if (externo) externo.removeEventListener("abort", propagarAbort);
    }
  }
  function leerCookie(nombre) {
    var prefijo = encodeURIComponent(nombre) + "=";
    var partes = String(document.cookie || "").split(";");
    for (var i = 0; i < partes.length; i += 1) {
      var parte = partes[i].trim();
      if (parte.indexOf(prefijo) === 0) {
        try { return decodeURIComponent(parte.slice(prefijo.length)); }
        catch (e) { return parte.slice(prefijo.length); }
      }
    }
    return "";
  }
  function csrfActual() { return leerCookie("csrftoken"); }
  function esMutacion(method) {
    return ["POST", "PUT", "PATCH", "DELETE"].indexOf(String(method || "GET").toUpperCase()) >= 0;
  }
  async function asegurarCsrf() {
    if (csrfActual()) return csrfActual();
    var r = await fetchConTimeout(apiUrl("/auth/csrf/"), {
      method: "GET",
      credentials: "same-origin",
      headers: { accept: "application/json" },
    });
    if (!r.ok) throw new Error("No se pudo inicializar la protección CSRF (error " + r.status + ").");
    var csrf = csrfActual();
    if (!csrf) throw new Error("El servidor no entregó la cookie CSRF.");
    return csrf;
  }
  function notificarSesionVencida() {
    limpiarSesion();
    if (_sesionVencidaNotificada) return;
    _sesionVencidaNotificada = true;
    if (_onSesionVencida) _onSesionVencida();
  }
  // Fetch de sesión same-origin. El CSRF se lee de document.cookie justo antes de CADA
  // mutación: Django lo rota al iniciar sesión y cachearlo dejaría logout/PATCH en 403.
  async function authedFetch(url, opts) {
    opts = Object.assign({}, opts || {});
    opts.credentials = "same-origin";
    opts.headers = Object.assign({}, opts.headers || {});
    if (esMutacion(opts.method)) {
      await asegurarCsrf();
      opts.headers["X-CSRFToken"] = csrfActual();
    }
    var r = await fetchConTimeout(url, opts);
    if (r.status === 401) {
      // No se reintenta una mutación: la sesión ya no existe y repetirla sería ambiguo.
      notificarSesionVencida();
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
    var r = await authedFetch(apiUrl(path), {});
    if (!r.ok) {
      // El status va como propiedad, no solo en el texto: quien llama distingue un 403 (el rol
      // no ve este recurso) de un fallo de red sin tener que parsear el mensaje.
      var e = new Error("GET " + path + " → " + r.status);
      e.status = r.status;
      throw e;
    }
    return r.json();
  }
  async function jsend(method, path, body) {
    var r = await authedFetch(apiUrl(path), {
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
    var rows = [], url = apiUrl(path);
    while (url) {
      var r = await authedFetch(url, {});
      if (!r.ok) throw new Error("GET " + path + " → " + r.status);
      var d = await r.json();
      rows = rows.concat(d.results || []);
      url = d.next ? apiUrl(d.next) : null;
    }
    return rows;
  }

  // Mapea la tarjeta de checklist del back ({tipo_proceso, sin_plantilla, items:[...]}) a la
  // forma que consume _chkView del componente. Resuelve el nombre del tipo de documento con el
  // catálogo ya cargado (_tipoDocByNombre) para que el ítem documental diga a qué doc se enlaza.
  function _mapTarjetaChecklist(t) {
    if (!t) return { hay: false };
    var nameById = {};
    Object.keys(_tipoDocByNombre).forEach(function (n) { nameById[_tipoDocByNombre[n].id] = n; });
    return {
      hay: true,
      tipo: t.tipo_proceso,
      sinPlantilla: !!t.sin_plantilla,
      items: (t.items || []).map(function (it) {
        return {
          id: it.id, etiqueta: it.etiqueta, tipo: it.tipo_item, hecho: !!it.hecho,
          doc: it.tipo_documento != null ? (nameById[it.tipo_documento] || "documento") : "",
        };
      }),
    };
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
  function nombreDeEmpleado(e) {
    return ((e && e.nombre || "") + " " + (e && e.apellido || "")).trim();
  }
  function etiquetaEmpleado(e) {
    var nombre = nombreDeEmpleado(e) || "Empleado";
    return e && e.legajo ? e.legajo + " · " + nombre : nombre;
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
  // Estado elegido en el alta → endpoint de decisión. "En proceso" y "Cerrada" se excluyen:
  // requieren las acciones explícitas Tomar/Cerrar desde el detalle.
  var ESTADONOV = { "Aprobada": "aprobar", "Rechazada": "rechazar", "Anulada": "anular" };
  function pedirMotivoDecision(accion) {
    if (accion !== "rechazar" && accion !== "anular") return "";
    var sustantivo = accion === "rechazar" ? "rechazo" : "anulación";
    var motivo = window.prompt("Ingresá el motivo de la " + sustantivo + " (obligatorio):", "");
    if (motivo === null) return null;  // Cancelar no dispara ninguna mutación.
    motivo = motivo.trim();
    if (!motivo) {
      showToast("El motivo de la " + sustantivo + " es obligatorio.", "error");
      return null;
    }
    return motivo;
  }

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
      id: e.id, legajo: e.legajo || "", nombre: e.nombre || "", apellido: e.apellido || "",
      name: nombreDeEmpleado(e), dni: e.dni,
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
      tieneFoto: !!e.tiene_foto,
      // metadatos para el cableado:
      _fotoUrl: e.foto_url || null,
      _relacionActivaId: activa.id || null, _empresaId: activa.empresa || null,
      _sectorId: activa.sector || null, _puestoId: activa.puesto || null,
      _supervisorId: activa.supervisor || null,
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

  function clavePuesto(sectorId, nombre) {
    return String(sectorId || "") + "|" + normLabel(nombre);
  }
  function puestoSeleccionado(sectorId, nombre) {
    nombre = (nombre || "").trim();
    if (!sectorId) throw new Error("Seleccioná el sector.");
    if (!nombre) throw new Error("Seleccioná un puesto.");
    var id = _puestoBySectorNombre[clavePuesto(sectorId, nombre)];
    var puesto = _puestosCat.find(function (p) { return p.id === id; });
    if (!puesto || !puesto.activo || Number(puesto.sector) !== Number(sectorId)) {
      throw new Error("El puesto elegido no está activo o no pertenece al sector seleccionado.");
    }
    return id;
  }
  // Busca una persona por DNI completo en el endpoint restringido y auditado. El listado
  // general ya no expone DNI (PII), por eso jamás se intenta inferir el reingreso desde ahí.
  async function findEmpleadoByDni(dni) {
    if (!dni) return null;
    try {
      return await jget("/empleados/por-dni/?dni=" + encodeURIComponent(dni));
    } catch (e) {
      if (e && e.status === 404) return null;
      throw e;
    }
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
      // El <input type=date> transparente es solo el disparador del calendario; comparte
      // etiqueta con el input de texto de al lado, así que rotularlo crea DOS controles con el
      // mismo nombre (MEDIO-01). Se lo saca del árbol accesible en neutralizarDatePickers.
      if (el.type === "date") return;
      if (el.getAttribute("aria-label")) return;
      var txt = labelFor(el).replace(/\s*·\s*$/, "").trim();
      if (txt) el.setAttribute("aria-label", txt);
    });
  }

  // MEDIO-01: cada campo de fecha es un input de texto (dd/mm/aaaa) + un <input type=date>
  // transparente encima que solo abre el calendario. Los dos se anunciaban como "Fecha", así
  // que el lector de pantalla veía dos textboxes por dato. El de texto ya es operable por
  // teclado (se escribe la fecha); el de date se saca del árbol y del tab order.
  function neutralizarDatePickers(sel) {
    var m = document.querySelector(sel);
    if (!m) return;
    m.querySelectorAll('input[type="date"]').forEach(function (el) {
      el.setAttribute("aria-hidden", "true");
      el.setAttribute("tabindex", "-1");
    });
  }

  // ---------- inert del fondo: login y modales (ALTO-03 / MEDIO-02) ----------
  // El login y los modales son overlays visuales (z-index) sobre la app, pero eso NO los saca
  // del árbol accesible: un lector de pantalla igual anuncia el sidebar, el header y todas las
  // acciones de atrás, y el Tab puede llevar el foco a controles tapados. `inert` los apaga de
  // verdad (foco + a11y). Se marcan solo las dos regiones de la app —el <aside> y la columna de
  // contenido— y NO los overlays, que son hermanos: así el login/modal de adelante sigue vivo.
  function _regionesApp() {
    var shell = document.querySelector(".ceibo-shell");
    if (!shell) return [];
    var aside = shell.querySelector(":scope > aside");
    var contenido = aside ? aside.nextElementSibling : null;   // el <div> de header+main
    return [aside, contenido].filter(Boolean);
  }
  function _fondoInerte(on) {
    _regionesApp().forEach(function (el) {
      if (on) { el.setAttribute("inert", ""); el.setAttribute("aria-hidden", "true"); }
      else { el.removeAttribute("inert"); el.removeAttribute("aria-hidden"); }
    });
  }

  // Marcador de "el rol no puede ver este módulo" (respuesta 403), distinto de `null` (que es
  // fallo de red / módulo sin cargar). Se compara por identidad, así que es un objeto único.
  var SIN_PERMISO = { __sinPermiso: true };

  // ---------- campos de la ficha que el guardado NO toca ----------
  // La edición combinada guarda persona + asignación en una transacción. Empresa, ingreso,
  // estado y supervisor conservan flujos propios; sector, puesto y jornada sí se actualizan
  // desde la ficha y quedan registrados en la bitácora.
  var EMPRESA_LOCK_MSG =
    "La empresa no se edita desde la ficha. Para mover al empleado a otra empresa, " +
    "registrá su salida (baja) y luego su reingreso.";
  var RELACION_LOCK_MSG =
    "La fecha de ingreso es parte de la vigencia y el supervisor se reasigna desde la ficha.";
  var DNI_LOCK_MSG = "El DNI identifica a la persona y no se edita desde la ficha.";
  var ESTADO_LOCK_MSG =
    "El estado no se elige a mano: sale de la relación laboral (activo mientras haya una " +
    "relación ACTIVA). Se cambia dando de baja o registrando el reingreso.";
  // Campos de la relación laboral, por etiqueta normalizada (las claves de readAltaForm).
  var CAMPOS_RELACION_BLOQUEADOS = ["supervisor", "fecha de ingreso"];

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
      "Sector, puesto y jornada se guardan junto con los datos personales. La empresa y " +
      "la fecha de ingreso conservan su historial; el supervisor se reasigna desde la ficha.";
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
  // Reconstruye las <option> de un <select> desde el catálogo, en vez de las hardcodeadas del
  // canvas. Sin esto, una empresa/sector creado por el ABM no aparecía para elegir en el alta.
  // `incluir` mete un valor extra aunque esté inactivo (para que la edición muestre el actual).
  function poblarSelectDesde(sel, nombres, incluir) {
    if (!sel || sel.tagName !== "SELECT") return;
    var lista = nombres.slice();
    if (incluir && incluir !== "—" && lista.indexOf(incluir) < 0) lista.push(incluir);
    sel.innerHTML = "";
    lista.forEach(function (n) {
      var o = document.createElement("option");
      o.value = n; o.textContent = n;
      sel.appendChild(o);
    });
  }
  function poblarSelectEmpresas(sel, incluir) {
    poblarSelectDesde(sel, _empresasCat.filter(function (e) { return e.activa; })
      .map(function (e) { return e.nombre; }), incluir);
  }
  function poblarSelectSectores(sel, incluir) {
    poblarSelectDesde(sel, _sectoresCat.filter(function (s) { return s.activo; })
      .map(function (s) { return s.nombre; }), incluir);
  }
  function poblarSelectPuestos(sel, sector, incluir) {
    if (!sel || sel.tagName !== "SELECT") return;
    var sectorId = typeof sector === "number" ? sector : _sectorByName[sector];
    var nombres = _puestosCat.filter(function (p) {
      return p.activo && Number(p.sector) === Number(sectorId);
    }).map(function (p) { return p.nombre; });
    poblarSelectDesde(sel, nombres, incluir);
    var vacia = document.createElement("option");
    vacia.value = "";
    vacia.textContent = sectorId ? "Seleccionar puesto…" : "Primero seleccioná un sector";
    sel.insertBefore(vacia, sel.firstChild);
    sel.value = incluir && nombres.indexOf(incluir) >= 0 ? incluir : "";
    sel.disabled = !sectorId;
  }
  function poblarSelectSupervisores(sel, incluir) {
    if (!sel || sel.tagName !== "SELECT") return;
    sel.replaceChildren();
    var vacia = document.createElement("option");
    vacia.value = "";
    vacia.textContent = "Sin supervisor asignado";
    sel.appendChild(vacia);
    _supervisoresCat.forEach(function (s) {
      var o = document.createElement("option");
      o.value = String(s.id);
      o.textContent = s.nombre_completo || s.username;
      sel.appendChild(o);
    });
    if (incluir != null && !_supervisoresCat.some(function (s) {
      return Number(s.id) === Number(incluir);
    })) {
      var legado = document.createElement("option");
      legado.value = String(incluir);
      legado.textContent = "Supervisor actual #" + incluir;
      sel.appendChild(legado);
    }
    sel.value = incluir == null ? "" : String(incluir);
  }
  // Mantiene el catálogo en memoria tras un alta/edición/baja, para que el dropdown de alta
  // refleje el cambio sin recargar toda la app.
  function _upsertEmpresaCat(e) {
    var row = { id: e.id, nombre: e.nombre, activa: !!e.activa };
    var i = _empresasCat.findIndex(function (x) { return x.id === e.id; });
    if (i >= 0) _empresasCat[i] = row; else _empresasCat.push(row);
  }
  function _upsertSectorCat(s) {
    var row = { id: s.id, nombre: s.nombre, activo: !!s.activo };
    var i = _sectoresCat.findIndex(function (x) { return x.id === s.id; });
    if (i >= 0) _sectoresCat[i] = row; else _sectoresCat.push(row);
  }
  function _reindexPuestos() {
    _puestoBySectorNombre = {};
    _puestoById = {};
    _puestosCat.forEach(function (p) {
      _puestoById[p.id] = p.nombre;
      if (p.sector != null) {
        _puestoBySectorNombre[clavePuesto(p.sector, p.nombre)] = p.id;
      }
    });
  }
  function _upsertPuestoCat(p) {
    var row = {
      id: p.id, nombre: p.nombre, sector: p.sector == null ? null : Number(p.sector),
      activo: !!p.activo,
    };
    var i = _puestosCat.findIndex(function (x) { return x.id === p.id; });
    if (i >= 0) _puestosCat[i] = row; else _puestosCat.push(row);
    _reindexPuestos();
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
    "El estado no se edita acá: se cambia con Tomar, Aprobar, Rechazar, Cerrar o Anular desde el detalle " +
    "de la novedad.";
  // El canvas ofrece los seis estados del dominio. El alta nace Registrada y puede encadenar
  // una decisión soportada, pero nunca simula "En proceso" ni "Cerrada": esas transiciones
  // registran actor y momento y se ejecutan desde el detalle.
  function podarEstadosNov(sel) {
    if (!sel || sel.tagName !== "SELECT") return;
    Array.prototype.slice.call(sel.options).forEach(function (o) {
      var v = o.value || o.textContent;
      if (v !== "Registrada" && !ESTADONOV[v]) o.remove();
    });
    sel.value = "Registrada";
  }
  function poblarSelectEmpleados(sel, seleccionado) {
    if (!sel || sel.tagName !== "SELECT") return;
    sel.replaceChildren();
    var vacia = document.createElement("option");
    vacia.value = "";
    vacia.textContent = "Seleccionar empleado…";
    sel.appendChild(vacia);
    _rawEmpleados.filter(function (e) { return e.activo; }).forEach(function (e) {
      var o = document.createElement("option");
      o.value = String(e.id);
      // `textContent` es deliberado: nombre/apellido son datos editables y nunca deben
      // convertirse en markup. El legajo permite distinguir homónimos sin mostrar PII.
      o.textContent = etiquetaEmpleado(e);
      sel.appendChild(o);
    });
    sel.value = seleccionado == null ? "" : String(seleccionado);
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
      if (d[c.key] && d[c.key].disponible === false) return null;
      var m = d[c.key] || { valor: 0, delta: 0 };
      var dl = kpiDelta(m.delta, c.goodUp);
      return {
        label: c.label, value: String(m.valor), sub: c.sub,
        delta: dl.txt, deltaStyle: dl.style,
        icon: (mockMetrics[i] && mockMetrics[i].icon) || "",
      };
    }).filter(Boolean);
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
    if (rot.disponible === false) {
      return {
        rotValor: "No disponible",
        rotDelta: "El equipo actual no tiene historial de asignación",
        rotDeltaStyle: "font-size:12px;color:var(--text3);font-weight:600",
        rotPeriodoLbl: "alcance: equipo actual",
        rotPoints: "",
        rotArea: "",
        rotDotX: 20,
        rotDotY: 160,
        rotLabels: [],
      };
    }
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

  // ---------- adaptador reportes (API → vars del diseño) ----------
  // Sparkline de dotación sobre el viewBox 0 0 560 200 del canvas (x: 20→540; el valor
  // más bajo cae en y=150 y el más alto en y=50, dentro de las líneas guía). El área se
  // cierra en y=180 (debajo del piso visible) para que el degradé llegue al borde.
  function repDotacion(dot) {
    var serie = (dot && dot.serie) || [];
    var vals = serie.map(function (p) { return p.valor; });
    var vmin = vals.length ? Math.min.apply(null, vals) : 0;
    var vmax = vals.length ? Math.max.apply(null, vals) : 0;
    var range = (vmax - vmin) || 1, n = serie.length || 1;
    var pts = serie.map(function (p, i) {
      var x = 20 + (n > 1 ? i * (520 / (n - 1)) : 0);
      var y = 150 - ((p.valor - vmin) / range) * 100;
      return { x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10 };
    });
    var pointsStr = pts.map(function (p) { return p.x + "," + p.y; }).join(" ");
    var first = pts[0] || { x: 20, y: 100 }, last = pts[pts.length - 1] || { x: 540, y: 100 };
    var area = "M" + first.x + ",180 L" + pts.map(function (p) { return p.x + "," + p.y; }).join(" L") +
      " L" + last.x + ",180 Z";
    var dp = (dot && dot.delta_pct) || 0, same = !dp, up = dp > 0;
    var color = same ? "var(--text3)" : (up ? "var(--ok)" : "var(--bad)");
    var deltaTxt = same ? "sin cambios" : ((up ? "▲ " : "▼ ") + fmtNum1(Math.abs(dp)) + "%");
    return {
      repDotTotal: String((dot && dot.total) || 0),
      repDotDelta: deltaTxt,
      repDotDeltaStyle: "font-size:12px;color:" + color + ";font-weight:600",
      repDotPoints: pointsStr, repDotArea: area, repDotX: last.x, repDotY: last.y,
      repDotLabels: serie.map(function (p) { return { label: p.label }; }),
    };
  }
  // Barras de ausentismo: el ancho es relativo al tipo más frecuente; el número es el %.
  function repAusentismo(aus) {
    var items = (aus && aus.items) || [];
    var max = items.reduce(function (a, it) { return Math.max(a, it.cantidad); }, 0) || 1;
    return items.map(function (it) {
      return {
        label: it.label, pct: it.pct + "%",
        bar: "height:100%;width:" + Math.round(it.cantidad / max * 100) +
          "%;border-radius:6px;background:var(--accent)",
      };
    });
  }
  // Dona de motivos de egreso. El canvas dibuja arcos sobre r=54 (circunferencia ≈339.29)
  // con `stroke-dasharray="<arco> <resto>"` y un `dashoffset` acumulado negativo. El arco
  // se calcula con la fracción exacta (cantidad/total), no con el % redondeado, así la dona
  // no queda con una ranura por el redondeo. La leyenda comparte el color por posición.
  var _PALETA_EGRESO = ["var(--accent)", "var(--accent2)", "var(--bad)", "var(--warn)",
    "var(--text3)", "var(--ok)"];
  function repEgresos(egr) {
    var items = (egr && egr.items) || [], total = (egr && egr.total) || 0;
    var C = 2 * Math.PI * 54, resto = Math.ceil(C + 1), cum = 0;
    var arcs = [], legend = [];
    items.forEach(function (it, i) {
      var color = _PALETA_EGRESO[i % _PALETA_EGRESO.length];
      var arco = total ? (it.cantidad / total) * C : 0;
      arcs.push({
        color: color,
        dash: (Math.round(arco * 10) / 10) + " " + resto,
        offset: "-" + (Math.round(cum * 10) / 10),
      });
      cum += arco;
      legend.push({
        label: it.label, pct: it.pct + "%",
        dot: "width:10px;height:10px;border-radius:3px;background:" + color + ";flex:none",
      });
    });
    return { repEgresoArcs: arcs, egresos: legend };
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

    // Se llama al abrir cada modal: rotula los campos, saca del árbol los date-pickers
    // duplicados, encierra el foco y apaga el fondo.
    a11yModal(sel) { rotularCampos(sel); neutralizarDatePickers(sel); focoAtrapado(sel); _fondoInerte(true); },
    // Al cerrar: devuelve el foco y reactiva el fondo (hay sesión; si no la hubiera, la app
    // ya estaría inerte por el login, y a11ySesion la maneja aparte).
    a11yCerrar() { focoDevuelto(); _fondoInerte(false); },
    // El login tapa la app entera: mientras no hay sesión, el fondo va inerte (ALTO-03).
    a11ySesion(haySesion) { _fondoInerte(!haySesion); },

    // Marcador y test de "sin permiso" (403): el componente los usa para no pisar los mocks
    // del canvas con datos que el rol no puede ver, y para mostrar el aviso en su lugar.
    SIN_PERMISO: SIN_PERMISO,
    esSinPermiso(x) { return x === SIN_PERMISO; },

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

    // ---------- formato de la bitácora (RP8) ----------
    // El backend manda ISO con offset (…T14:32:10-03:00). `new Date` lo interpreta bien y
    // `toLocale*` lo pasa a la hora local del navegador, que es la que el usuario reconoce
    // como "cuándo pasó". Formatear a mano cortando el string dejaría la hora en UTC.
    fechaCorta(iso) {
      if (!iso) return "";
      var d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso);
      return d.toLocaleDateString("es-AR", { day: "2-digit", month: "2-digit", year: "numeric" });
    },
    horaCorta(iso) {
      if (!iso) return "";
      var d = new Date(iso);
      if (isNaN(d.getTime())) return "";
      // hour12:false explícito: es-AR devuelve "11:19 p. m." por default, y acá se leen
      // horarios laborales uno debajo del otro — el reloj de 24 h se compara de un vistazo.
      return d.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hour12: false });
    },

    // Un valor vacío en un diff no es lo mismo que el texto "": mostrarlo en blanco haría
    // leer "teléfono:  → 2664…" como si faltara algo. El guion dice "no había nada".
    valorLegible(v) {
      if (v === null || v === undefined || v === "") return "—";
      if (v === true) return "Sí";
      if (v === false) return "No";
      return String(v);
    },

    // Color por FAMILIA de acción, no por acción: son 23 y crecen. Lo que el ojo necesita
    // distinguir de un vistazo es qué se destruyó (rojo), qué se aprobó (verde) y qué se
    // creó (acento); el resto es una edición y va neutra.
    estiloAccion(accion) {
      var base = "display:inline-block;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap;";
      var a = String(accion || "");
      var color = "background:var(--surface2);color:var(--text2)";
      if (/RECHAZADA|ANULADA|ELIMINAD|FINALIZADA|DESACTIVADO|REVERTIDO/.test(a)) {
        color = "background:var(--bad-dim,rgba(248,113,113,.14));color:var(--bad)";
      } else if (/APROBADA|COMPLETADO/.test(a)) {
        color = "background:var(--ok-dim,rgba(52,211,153,.14));color:var(--ok)";
      } else if (/CREAD|CREAR|AGREGADO|PRORROGADA/.test(a)) {
        color = "background:var(--accent-dim);color:var(--accent)";
      }
      return base + color;
    },

    // ---------- sesión (A1) ----------
    // Antes acá había un usuario y una clave de superusuario hardcodeados: cualquiera que
    // abriera el front era admin y los roles del backend no protegían nada. Ahora la
    // sesión la abre una persona con sus credenciales.
    onSesionVencida(cb) { _onSesionVencida = cb; },

    haySesion() { return !!_perfil; },
    perfil() { return _perfil; },

    // Capacidades del rol (A5): qué acciones de escritura habilita, calculadas por el
    // backend (common/capacidades.py) y servidas en /mi/perfil/. El front las usa SOLO
    // para esconder botones; la seguridad real es el 403 del backend. Default restrictivo:
    // sin perfil o sin el objeto (sesión vieja, rol sin permisos), todo en false, así que
    // Empleado/Servicio no ven acciones de escritura en vez de verlas y comerse un 403.
    capacidades() { return (_perfil && _perfil.capacidades) || {}; },
    puede(clave) { return !!this.capacidades()[clave]; },

    async login(usuario, clave) {
      // El primer CSRF habilita el POST de login. Django lo rota al autenticar, por eso
      // no se conserva esta variable para pedidos posteriores: authedFetch relee la cookie.
      await asegurarCsrf();
      var r = await fetchConTimeout(apiUrl("/auth/login/"), {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "content-type": "application/json",
          "X-CSRFToken": csrfActual(),
        },
        body: JSON.stringify({ username: usuario, password: clave }),
      });
      if (!r.ok) {
        limpiarSesion();
        // 401 = credenciales; 429 = el throttle de login (5/min). Se distinguen porque el
        // usuario no puede hacer nada con "error 429", pero sí con "esperá un minuto".
        if (r.status === 429) throw new Error("Demasiados intentos. Esperá un minuto y probá de nuevo.");
        if (r.status === 401) throw new Error("Usuario o contraseña incorrectos.");
        if (r.status === 403) throw new Error("La protección de sesión venció. Recargá e intentá de nuevo.");
        throw new Error("No se pudo iniciar sesión (error " + r.status + ").");
      }
      var d = await r.json().catch(function () { return {}; });
      if (!d.username) throw new Error("El servidor no devolvió un perfil válido.");
      _perfil = d;
      _sesionVencidaNotificada = false;
      return _perfil;
    },

    // Reabre la sesión al recargar: el navegador manda la cookie HttpOnly y /mi/perfil/
    // confirma si sigue vigente. No hay credenciales copiadas en storage ni en memoria JS.
    async restaurarSesion() {
      try {
        await asegurarCsrf();
        await this.cargarPerfil();
      } catch (e) {
        limpiarSesion();
        return false;
      }
      _sesionVencidaNotificada = false;
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
      // El superusuario tiene acceso total por bypass (tiene_rol lo cortocircuita), pero no
      // pertenece a ningún grupo, así que roles viene vacío. Sin esto el pie decía "Sin rol
      // asignado", que parece un error de permisos justo en quien más tiene (MENOR-01).
      var rol = roles.length ? roles.join(" · ")
        : (_perfil.is_superuser ? "Administrador" : "Sin rol asignado");
      return {
        nombre: nombre || _perfil.username || "—",
        rol: rol,
      };
    },

    async logout(remoto) {
      // Ante un 401 la UI ya sabe que la sesión murió y llama con `false`: no tiene sentido
      // intentar cerrar en el servidor otra vez. El botón normal siempre hace POST real.
      if (remoto !== false) {
        await asegurarCsrf();
        var r = await fetchConTimeout(apiUrl("/auth/logout/"), {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRFToken": csrfActual() },
        });
        if (!r.ok && r.status !== 401) {
          throw new Error("No se pudo cerrar la sesión (error " + r.status + ").");
        }
      }
      limpiarSesion();
      _sesionVencidaNotificada = false;
      // Los índices de la sesión anterior no pueden sobrevivir al cambio de usuario: el
      // que entre después ve lo que su rol permita, no lo que quedó cacheado del anterior.
      _empresaByName = {}; _empresaById = {};
      _sectorByName = {}; _sectorById = {};
      _puestoBySectorNombre = {}; _puestoById = {};
      _empresasCat = []; _sectoresCat = []; _puestosCat = []; _supervisoresCat = [];
      _rawEmpleados = []; _empById = {}; _empresaByRelacionId = {};
      _tipoNovByCodigo = {}; _novRawById = {}; _tipoDocByNombre = {}; _docsByEmp = {};
      revocarTodasLasFotos();   // los blobs de foto del usuario anterior no sobreviven al logout
    },

    async init() {
      var emp = await getAllPages("/empresas/?page_size=100");
      var sec = await getAllPages("/sectores/?page_size=100");
      var pue = await getAllPages("/puestos/?page_size=100");
      emp.forEach(function (x) { _empresaByName[x.nombre] = x.id; _empresaById[x.id] = x.nombre; });
      sec.forEach(function (x) { _sectorByName[x.nombre] = x.id; _sectorById[x.id] = x.nombre; });
      _empresasCat = emp.map(function (x) { return { id: x.id, nombre: x.nombre, activa: !!x.activa }; });
      _sectoresCat = sec.map(function (x) { return { id: x.id, nombre: x.nombre, activo: !!x.activo }; });
      _puestosCat = pue.map(function (x) {
        return { id: x.id, nombre: x.nombre, sector: x.sector, activo: !!x.activo };
      });
      _reindexPuestos();
      var tipos = await getAllPages("/tipos-novedad/?page_size=100");
      tipos.forEach(function (t) { _tipoNovByCodigo[t.codigo] = t; });
      // El catálogo está restringido a RRHH/Admin. Los demás roles no lo necesitan y no
      // deben romper su carga inicial por recibir el 403 esperado.
      if (_perfil && _perfil.capacidades && _perfil.capacidades.empleados_escribir) {
        try {
          var supervisores = await jget("/supervisores/?activo=true");
          _supervisoresCat = Array.isArray(supervisores) ? supervisores : [];
        } catch (e) {
          console.warn("[ceibo] catálogo de supervisores no disponible", e);
          _supervisoresCat = [];
        }
      }
      console.log("[ceibo] catálogos: " + emp.length + " empresas, " + sec.length + " sectores, " + pue.length + " puestos, " + tipos.length + " tipos de novedad");
    },

    async listEmpleados() {
      _rawEmpleados = await getAllPages("/empleados/?page_size=100");
      var mapped = _rawEmpleados.map(adapt);
      _empById = {};
      mapped.forEach(function (m) {
        _empById[m.id] = {
          id: m.id, legajo: m.legajo, nombre: m.nombre, apellido: m.apellido,
          name: m.name, label: (m.legajo ? m.legajo + " · " : "") + m.name,
          empresa: m.empresa,
        };
      });
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

    // El listado es deliberadamente un resumen sin PII. La ficha pide el detalle por el
    // endpoint `retrieve`, que además deja constancia EMPLEADO_CONSULTADO en la bitácora.
    async getEmpleado(id) {
      var raw = await jget("/empleados/" + id + "/");
      var pos = _rawEmpleados.findIndex(function (e) { return e.id === raw.id; });
      if (pos >= 0) _rawEmpleados[pos] = raw; else _rawEmpleados.push(raw);
      var mapped = adapt(raw);
      mapped._detalleCargado = true;
      _empById[mapped.id] = {
        id: mapped.id, legajo: mapped.legajo, nombre: mapped.nombre, apellido: mapped.apellido,
        name: mapped.name, label: (mapped.legajo ? mapped.legajo + " · " : "") + mapped.name,
        empresa: mapped.empresa,
      };
      (raw.relaciones || []).forEach(function (r) {
        _empresaByRelacionId[r.id] = _empresaById[r.empresa] || "—";
      });
      return mapped;
    },

    // Métricas del panel general. Devuelve el dict crudo del backend (o null si el
    // rol no tiene panel / falla la red); el componente lo pasa por dashboardVals.
    async loadDashboard() {
      try { return await jget("/dashboard/metricas/"); }
      catch (e) {
        if (e && e.status === 403) return SIN_PERMISO;   // el rol no ve el panel: NO caer en mocks
        console.warn("[ceibo] dashboard no disponible", e); return null;
      }
    },
    // Traduce la respuesta del backend a las vars del diseño (metrics, rankFaltas,
    // rotación). `mockMetrics` aporta solo los íconos SVG del canvas.
    dashboardVals(d, rotState, mockMetrics) {
      var out = { metrics: dashMetrics(d, mockMetrics), rankFaltas: dashRank(d) };
      return Object.assign(out, dashRotacion(d, rotState || "m"));
    },

    // Métricas de Reportes (dotación en el tiempo, ausentismo por tipo, motivos de egreso).
    // Igual que el dashboard: dict crudo del backend, o null si el rol no ve la dotación.
    async loadReportes() {
      try { return await jget("/reportes/metricas/"); }
      catch (e) {
        if (e && e.status === 403) return SIN_PERMISO;
        console.warn("[ceibo] reportes no disponibles", e); return null;
      }
    },
    // Traduce la respuesta a las vars del diseño: dotación (sparkline + total + variación),
    // ausentismo (barras) y egresos (dona + leyenda).
    reportesVals(d) {
      d = d || {};
      return Object.assign(
        {}, repDotacion(d.dotacion || {}),
        { ausentismo: repAusentismo(d.ausentismo || {}) },
        repEgresos(d.egresos || {}),
      );
    },

    // Vencimientos de toda la dotación (documentos + contratos). Como el dashboard:
    // devuelve el dict crudo, o null si el rol no ve la dotación / falla la red.
    async loadVencimientos() {
      try { return await jget("/alertas/vencimientos/"); }
      catch (e) {
        if (e && e.status === 403) return SIN_PERMISO;
        console.warn("[ceibo] vencimientos no disponibles", e); return null;
      }
    },

    // Alertas del día (tarjeta del panel): vencimientos + certificados + cumpleaños.
    async loadAlertasDia() {
      try { return await jget("/alertas/del-dia/"); }
      catch (e) {
        if (e && e.status === 403) return SIN_PERMISO;
        console.warn("[ceibo] alertas del día no disponibles", e); return null;
      }
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
      catch (e) {
        if (e && e.status === 403) return SIN_PERMISO;
        console.warn("[ceibo] config de vencimientos no disponible", e); return null;
      }
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
              // Sin fecha es rojo (bad) igual, pero no es "Vencido": no se sabe cuándo vence,
              // es documentación incompleta. El rótulo lo dice; el color no cambia (MEDIO-05).
              label: (i.estado === "bad" && !i.fecha) ? "Sin fecha" : ui.semLabel(i.estado),
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

    // ---------- Empresas (ABM en Configuración) ----------
    // El backend ya soporta alta (POST), edición (PATCH) y baja lógica (activa=false); no hay
    // DELETE físico a propósito. Solo RRHH/Admin escriben (el 403 es la seguridad real; el
    // canvas esconde los botones por capacidad, igual que el resto).
    // Trae TODAS las empresas (activas e inactivas) para poder reactivar una dada de baja.
    async listEmpresas() {
      var rows = await getAllPages("/empresas/?page_size=100");
      rows.forEach(function (x) { _empresaByName[x.nombre] = x.id; _empresaById[x.id] = x.nombre; });
      _empresasCat = rows.map(function (x) { return { id: x.id, nombre: x.nombre, activa: !!x.activa }; });
      return rows.map(function (e) {
        return {
          id: e.id,
          nombre: e.nombre,
          razon_social: e.razon_social || "",
          cuit: e.cuit || "",
          activa: !!e.activa,
        };
      });
    },

    // `datos`: { nombre, razon_social, cuit }. Solo `nombre` es obligatorio (lo pide el modelo).
    async crearEmpresa(datos) {
      var nombre = (datos && datos.nombre || "").trim();
      if (!nombre) throw new Error("El nombre de la empresa es obligatorio.");
      var body = { nombre: nombre, razon_social: (datos.razon_social || "").trim(), cuit: (datos.cuit || "").trim() };
      var e = await jsend("POST", "/empresas/", body);
      _empresaByName[e.nombre] = e.id; _empresaById[e.id] = e.nombre;   // el dropdown de alta la ve al toque
      _upsertEmpresaCat(e);
      showToast("Empresa creada", "ok");
      return e;
    },

    async editarEmpresa(id, datos) {
      var body = {};
      ["nombre", "razon_social", "cuit"].forEach(function (k) {
        if (datos && datos[k] != null) body[k] = String(datos[k]).trim();
      });
      if (body.nombre === "") throw new Error("El nombre de la empresa no puede quedar vacío.");
      var e = await jsend("PATCH", "/empresas/" + id + "/", body);
      _empresaById[e.id] = e.nombre; _empresaByName[e.nombre] = e.id;
      _upsertEmpresaCat(e);
      showToast("Empresa actualizada", "ok");
      return e;
    },

    // Baja/reactivación lógica: no borra, solo apaga la empresa (activa=false). Las relaciones
    // laborales viejas la siguen nombrando; una empresa inactiva no se ofrece para altas nuevas.
    async toggleEmpresaActiva(id, activa) {
      var e = await jsend("PATCH", "/empresas/" + id + "/", { activa: !!activa });
      _upsertEmpresaCat(e);
      showToast(activa ? "Empresa reactivada" : "Empresa dada de baja", "ok");
      return e;
    },

    // ---------- Sectores (ABM en Configuración) ----------
    // Mismo patrón que empresa: el SectorViewSet ya soporta POST/PATCH y baja lógica (activo).
    // El sector es transversal al grupo (no cuelga de una empresa). Solo tiene nombre y estado.
    async listSectores() {
      var rows = await getAllPages("/sectores/?page_size=100");
      rows.forEach(function (x) { _sectorByName[x.nombre] = x.id; _sectorById[x.id] = x.nombre; });
      _sectoresCat = rows.map(function (x) { return { id: x.id, nombre: x.nombre, activo: !!x.activo }; });
      return rows.map(function (s) { return { id: s.id, nombre: s.nombre, activo: !!s.activo }; });
    },

    async crearSector(datos) {
      var nombre = (datos && datos.nombre || "").trim();
      if (!nombre) throw new Error("El nombre del sector es obligatorio.");
      var s = await jsend("POST", "/sectores/", { nombre: nombre });
      _sectorByName[s.nombre] = s.id; _sectorById[s.id] = s.nombre;
      _upsertSectorCat(s);
      showToast("Sector creado", "ok");
      return s;
    },

    async editarSector(id, datos) {
      var nombre = (datos && datos.nombre != null) ? String(datos.nombre).trim() : "";
      if (!nombre) throw new Error("El nombre del sector no puede quedar vacío.");
      var s = await jsend("PATCH", "/sectores/" + id + "/", { nombre: nombre });
      _sectorById[s.id] = s.nombre; _sectorByName[s.nombre] = s.id;
      _upsertSectorCat(s);
      showToast("Sector actualizado", "ok");
      return s;
    },

    async toggleSectorActivo(id, activo) {
      var s = await jsend("PATCH", "/sectores/" + id + "/", { activo: !!activo });
      _upsertSectorCat(s);
      showToast(activo ? "Sector reactivado" : "Sector dado de baja", "ok");
      return s;
    },

    // ---------- Puestos por sector (ABM en Configuración) ----------
    // No se crean puestos implícitamente al dar de alta una persona: primero se parametrizan
    // acá y luego el alta ofrece exclusivamente los activos del sector elegido.
    async listPuestos() {
      var rows = await getAllPages("/puestos/?page_size=100");
      _puestosCat = rows.map(function (p) {
        return { id: p.id, nombre: p.nombre, sector: p.sector, activo: !!p.activo };
      });
      _reindexPuestos();
      return _puestosCat.map(function (p) {
        return {
          id: p.id, nombre: p.nombre, sector: p.sector,
          sector_nombre: _sectorById[p.sector] || "—", activo: p.activo,
        };
      });
    },

    async crearPuesto(datos) {
      var nombre = String(datos && datos.nombre || "").trim();
      var sector = Number(datos && datos.sector);
      if (!nombre) throw new Error("El nombre del puesto es obligatorio.");
      if (!sector || !_sectorById[sector]) throw new Error("Seleccioná el sector del puesto.");
      var p = await jsend("POST", "/puestos/", { nombre: nombre, sector: sector });
      _upsertPuestoCat(p);
      showToast("Puesto creado", "ok");
      return p;
    },

    async editarPuesto(id, datos) {
      var nombre = String(datos && datos.nombre || "").trim();
      var sector = Number(datos && datos.sector);
      if (!nombre) throw new Error("El nombre del puesto no puede quedar vacío.");
      if (!sector || !_sectorById[sector]) throw new Error("Seleccioná el sector del puesto.");
      var p = await jsend("PATCH", "/puestos/" + id + "/", {
        nombre: nombre, sector: sector,
      });
      _upsertPuestoCat(p);
      showToast("Puesto actualizado", "ok");
      return p;
    },

    async togglePuestoActivo(id, activo) {
      var p = await jsend("PATCH", "/puestos/" + id + "/", { activo: !!activo });
      _upsertPuestoCat(p);
      showToast(activo ? "Puesto reactivado" : "Puesto dado de baja", "ok");
      return p;
    },

    catalogosUI() {
      return {
        empresas: _empresasCat.filter(function (e) { return e.activa; }).map(function (e) {
          return { id: e.id, nombre: e.nombre };
        }),
        sectores: _sectoresCat.filter(function (s) { return s.activo; }).map(function (s) {
          return { id: s.id, nombre: s.nombre };
        }),
        supervisores: _supervisoresCat.map(function (s) {
          return {
            id: s.id,
            nombre: s.nombre_completo || s.username,
          };
        }),
      };
    },

    async asignarSupervisor(empleadoId, relacionId, supervisorId) {
      if (!empleadoId || !relacionId) throw new Error("El empleado no tiene relación activa.");
      var relacion = await jsend(
        "PATCH",
        "/empleados/" + empleadoId + "/relaciones/" + relacionId + "/supervisor/",
        { supervisor: supervisorId ? Number(supervisorId) : null }
      );
      showToast(supervisorId ? "Supervisor asignado" : "Supervisor quitado", "ok");
      return relacion;
    },

    // ---------- Tipos de documento (ABM en Configuración — CU-31) ----------
    // Mismo patrón que empresa/sector: el TipoDocumentoViewSet ya soporta GET/POST/PATCH y baja
    // lógica (activo), restringido a Admin/RRHH. La diferencia con listTiposDoc() —que trae solo
    // los activos para el dropdown de "Cargar documento"— es que el ABM lista TODOS (activos e
    // inactivos) para poder reactivar. `dias_aviso` se edita en "Parametría de alertas"; acá se
    // muestra como dato (un tipo nuevo nace en 30 por el default del modelo).
    // ===== Bitácora / auditoría (RP8) =====================================================
    // Solo Admin: el backend devuelve 403 a cualquier otro rol. El front además esconde la
    // entrada del menú con la capacidad `auditoria_ver` — eso es honestidad visual, no
    // seguridad; el 403 sigue estando.
    //
    // A diferencia del resto de los listados, acá NO se usa `getAllPages`: la bitácora crece
    // sin techo (cada alta, edición y aprobación suma un renglón), así que traerla entera
    // sería descargar el historial completo del sistema para mostrar 25 líneas. Se pide una
    // página por vez y se devuelve el total para paginar.
    //
    // `filtros`: { empleado, entidad, objeto_id, usuario, accion, desde, hasta, page }.
    async listAuditoria(filtros) {
      var f = filtros || {};
      var qs = [];
      ["empleado", "entidad", "objeto_id", "usuario", "accion", "desde", "hasta", "page"]
        .forEach(function (k) {
          var v = f[k];
          if (v !== undefined && v !== null && String(v).trim() !== "") {
            qs.push(encodeURIComponent(k) + "=" + encodeURIComponent(String(v).trim()));
          }
        });
      var d = await jget("/auditoria/registros/" + (qs.length ? "?" + qs.join("&") : ""));
      return {
        total: d.count || 0,
        hayMas: !!d.next,
        hayAnterior: !!d.previous,
        registros: (d.results || []).map(function (r) {
          return {
            id: r.id,
            momento: r.momento,
            // El backend ya congela el nombre del autor: si el usuario se borró, la
            // bitácora igual dice quién fue. Solo queda el caso del proceso automático.
            quien: r.usuario_nombre || "Sistema",
            accion: r.accion,
            accionLabel: r.accion_display || r.accion,
            entidad: r.entidad,
            objetoId: r.objeto_id,
            objeto: r.objeto_repr || "",
            empleadoId: r.empleado,
            empleado: r.empleado_nombre || "",
            // Ya viene como [{campo, antes, despues}] desde la API: el front no tiene que
            // cruzar dos diccionarios para saber qué cambió.
            cambios: r.cambios || [],
          };
        }),
      };
    },

    async listTiposDocCfg() {
      var rows = await getAllPages("/tipos-documento/?page_size=100");
      return rows.map(function (t) {
        return {
          id: t.id,
          nombre: t.nombre,
          descripcion: t.descripcion || "",
          dias_aviso: t.dias_aviso,
          activo: !!t.activo,
        };
      });
    },

    // `datos`: { nombre, descripcion }. Solo `nombre` es obligatorio (lo pide el modelo, unique).
    async crearTipoDoc(datos) {
      var nombre = (datos && datos.nombre || "").trim();
      if (!nombre) throw new Error("El nombre del tipo de documento es obligatorio.");
      var body = { nombre: nombre, descripcion: (datos.descripcion || "").trim() };
      var t = await jsend("POST", "/tipos-documento/", body);
      showToast("Tipo de documento creado", "ok");
      return t;
    },

    async editarTipoDoc(id, datos) {
      var body = {};
      ["nombre", "descripcion"].forEach(function (k) {
        if (datos && datos[k] != null) body[k] = String(datos[k]).trim();
      });
      if (body.nombre === "") throw new Error("El nombre del tipo de documento no puede quedar vacío.");
      var t = await jsend("PATCH", "/tipos-documento/" + id + "/", body);
      showToast("Tipo de documento actualizado", "ok");
      return t;
    },

    // Baja/reactivación lógica: no borra, solo apaga el tipo (activo=false). Los documentos ya
    // cargados que lo usan no se rompen; un tipo inactivo no se ofrece para documentos nuevos.
    async toggleTipoDocActivo(id, activo) {
      var t = await jsend("PATCH", "/tipos-documento/" + id + "/", { activo: !!activo });
      showToast(activo ? "Tipo de documento reactivado" : "Tipo de documento dado de baja", "ok");
      return t;
    },

    // ---------- Checklists de ingreso/egreso (ABM en Configuración — CU-29/30) ----------
    // Cada alcance es empresa + sector (o General) + tipo de proceso. Se elige primero el
    // borrador editable; si no existe, la versión publicada queda visible pero inmutable.
    async listChecklist(empresaNombre, sectorId, tipoProceso) {
      var empId = _empresaByName[empresaNombre];
      var sector = sectorId === "" || sectorId == null ? null : Number(sectorId);
      if (empId == null) {
        var primera = _empresasCat.filter(function (e) { return e.activa; })[0];
        if (!primera) return { plantillaId: null, items: [], version: null, estado: null };
        empId = primera.id;
        empresaNombre = primera.nombre;
      }
      var rows = await getAllPages("/onboarding/plantillas/?empresa=" + empId +
        "&tipo_proceso=" + tipoProceso + "&page_size=100");
      rows = rows.filter(function (p) {
        return String(p.sector == null ? "" : p.sector) === String(sector == null ? "" : sector);
      }).sort(function (a, b) { return Number(b.version || 0) - Number(a.version || 0); });
      var pl = rows.filter(function (p) { return p.estado === "BORRADOR"; })[0] ||
        rows.filter(function (p) { return p.estado === "PUBLICADA"; })[0] || rows[0];
      if (!pl) {
        return {
          empresaNombre: empresaNombre, plantillaId: null, items: [],
          version: null, estado: null, puedeEditar: true,
        };
      }
      var items = (pl.items || []).map(function (it) {
        return {
          id: it.id, etiqueta: it.etiqueta, tipo: it.tipo_item,
          doc: it.tipo_documento_nombre || "", tipo_documento: it.tipo_documento, activo: !!it.activo,
        };
      });
      return {
        empresaNombre: empresaNombre, plantillaId: pl.id, items: items,
        version: pl.version, estado: pl.estado, puedeEditar: pl.estado === "BORRADOR",
      };
    },

    // Crea (o recupera) el borrador del alcance. Si ya hay una publicada, el backend copia
    // sus ítems en la nueva versión para que editar nunca cambie procesos ya iniciados.
    async crearPlantillaChecklist(empresaNombre, sectorId, tipoProceso) {
      var empId = _empresaByName[empresaNombre];
      if (empId == null) throw new Error("Empresa desconocida.");
      var body = { empresa: empId, tipo_proceso: tipoProceso };
      if (sectorId !== "" && sectorId != null) body.sector = Number(sectorId);
      var pl = await jsend("POST", "/onboarding/plantillas/", body);
      showToast("Borrador v" + pl.version + " listo para editar", "ok");
      return pl;
    },

    async publicarPlantillaChecklist(plantillaId) {
      if (!plantillaId) throw new Error("No hay un borrador para publicar.");
      var pl = await jsend("POST", "/onboarding/plantillas/" + plantillaId + "/publicar/", {});
      showToast("Checklist v" + pl.version + " publicado", "ok");
      return pl;
    },

    async archivarPlantillaChecklist(plantillaId) {
      if (!plantillaId) throw new Error("No hay una plantilla para archivar.");
      var pl = await jsend("POST", "/onboarding/plantillas/" + plantillaId + "/archivar/", {});
      showToast("Checklist v" + pl.version + " archivado", "ok");
      return pl;
    },

    // `datos`: { etiqueta, tipo: 'ACCION'|'DOCUMENTAL', tipo_documento: id|null }
    async agregarChecklistItem(plantillaId, datos) {
      var etiqueta = (datos && datos.etiqueta || "").trim();
      if (!etiqueta) throw new Error("El nombre del ítem es obligatorio.");
      var body = { etiqueta: etiqueta, tipo_item: datos.tipo };
      if (datos.tipo === "DOCUMENTAL") {
        if (!datos.tipo_documento) throw new Error("Elegí el documento que completa el ítem.");
        body.tipo_documento = datos.tipo_documento;
      }
      var it = await jsend("POST", "/onboarding/plantillas/" + plantillaId + "/items/", body);
      showToast("Ítem agregado", "ok");
      return it;
    },

    async editarChecklistItem(plantillaId, itemId, datos) {
      var body = {};
      if (datos.etiqueta != null) {
        body.etiqueta = String(datos.etiqueta).trim();
        if (!body.etiqueta) throw new Error("El nombre del ítem no puede quedar vacío.");
      }
      if (datos.tipo != null) {
        body.tipo_item = datos.tipo;
        if (datos.tipo === "DOCUMENTAL") {
          if (!datos.tipo_documento) throw new Error("Elegí el documento que completa el ítem.");
          body.tipo_documento = datos.tipo_documento;
        } else {
          body.tipo_documento = null;
        }
      }
      var it = await jsend("PATCH", "/onboarding/plantillas/" + plantillaId + "/items/" + itemId + "/", body);
      showToast("Ítem actualizado", "ok");
      return it;
    },

    // Baja/reactivación lógica del ítem (activo). No borra: un proceso ya creado lo fotografió.
    async toggleChecklistItem(plantillaId, itemId, activo) {
      var it = await jsend("PATCH", "/onboarding/plantillas/" + plantillaId + "/items/" + itemId + "/", { activo: !!activo });
      showToast(activo ? "Ítem reactivado" : "Ítem quitado", "ok");
      return it;
    },

    // ---------- Tarjeta de checklist en la ficha (CU-29/30) ----------
    // GET es lectura pura. Si no hay proceso devuelve los datos necesarios para que RRHH lo
    // inicie con una acción explícita; abrir la ficha nunca crea estado de negocio.
    async getChecklistFicha(empleadoId) {
      var r = await jget("/empleados/" + empleadoId + "/checklist/");
      if (r && r.tarjeta) return _mapTarjetaChecklist(r.tarjeta);
      return {
        hay: false,
        puedeIniciar: !!(r && r.puede_iniciar),
        relacionId: r && r.relacion_laboral,
        tipoProceso: r && r.tipo_proceso,
      };
    },

    async iniciarChecklistFicha(empleadoId, datos) {
      if (!datos || !datos.relacionId || !datos.tipoProceso) {
        throw new Error("No se pudo determinar qué relación y proceso iniciar.");
      }
      var r = await jsend("POST", "/empleados/" + empleadoId + "/checklist/", {
        relacion_laboral: Number(datos.relacionId),
        tipo_proceso: datos.tipoProceso,
      });
      showToast(datos.tipoProceso === "EGRESO" ? "Offboarding iniciado" : "Onboarding iniciado", "ok");
      return _mapTarjetaChecklist(r && r.tarjeta);
    },

    async tildarChecklistFichaItem(empleadoId, itemId, hecho) {
      var r = await jsend("POST", "/empleados/" + empleadoId + "/checklist/items/" + itemId + "/tildar/", { hecho: !!hecho });
      return _mapTarjetaChecklist(r && r.tarjeta);
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
          // La fuente canónica es el cálculo del backend: solo APROBADA/CERRADA extiende
          // la vigencia. Recalcular acá incluía por error registradas o rechazadas.
          var vigHasta = (m.vigencia_efectiva && m.vigencia_efectiva.hasta) || m.fecha_hasta;
          out.fecha = fmtRango(m.fecha_desde, vigHasta);
        }
        return out;
      });
      console.log("[ceibo] novedades: " + rows.length + " cadenas");
      return rows;
    },

    // Prepara el alta de novedad: empleado identificado por ID (la etiqueta muestra
    // legajo + nombre), fecha por defecto = hoy y fin estimada recalculada con los días.
    populateNovForm() {
      if (!document.querySelector('[data-modal="altanov"]')) return;
      var f = readModalForm('[data-modal="altanov"]');
      var empEl = f["empleado"];
      // Solo empleados ACTIVOS: no se cargan novedades nuevas sobre egresados (el backend
      // también lo rechaza). Las opciones se crean como nodos, nunca con `innerHTML`.
      poblarSelectEmpleados(empEl, null);
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
      var empId = empEl && empEl.tagName === "SELECT" ? empEl.value : "";
      if (!empId || !_empById[empId]) {
        throw new Error("Empleado inválido: elegí un legajo de la lista.");
      }
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
      // Se pide ANTES de crear: cancelar un rechazo/anulación desde el alta no puede dejar
      // una novedad registrada a medias ni obligar al usuario a adivinar qué ocurrió.
      var motivoDecision = pedirMotivoDecision(accion);
      if ((accion === "rechazar" || accion === "anular") && motivoDecision === null) return false;
      var nov = await jsend("POST", "/novedades/", payload);
      if (accion) {
        // La novedad YA existe: si la transición falla hay que decirlo con todas las letras.
        // Un "error" a secas invita a reintentar el alta, y eso duplicaría el registro.
        try {
          var decisionBody = motivoDecision ? { motivo: motivoDecision } : {};
          await jsend("POST", "/novedades/" + nov.id + "/" + accion + "/", decisionBody);
        } catch (e) {
          throw new Error('La novedad se registró, pero no se pudo pasar a "' + estadoSel +
            '": ' + e.message + ". No la cargues de nuevo: cambiale el estado desde el detalle.");
        }
      }
      if (cert) await adjuntarCertificado(nov.id, cert, "La novedad se registró");
      showToast("Novedad registrada", "ok");
      return true;
    },

    // Transición de estado por endpoint dedicado. La lista cerrada impide que un valor
    // de UI termine convertido accidentalmente en un path arbitrario.
    async transicionNov(id, accion, motivo) {
      if (!id) throw new Error("no hay novedad seleccionada");
      var permitidas = ["tomar", "aprobar", "rechazar", "cerrar", "anular"];
      if (permitidas.indexOf(accion) < 0) throw new Error("transición de novedad inválida");
      var body = {};
      if (accion === "rechazar" || accion === "anular") {
        motivo = motivo == null ? pedirMotivoDecision(accion) : String(motivo).trim();
        if (!motivo) return false;
        body.motivo = motivo;
      }
      if (accion === "cerrar") {
        var actual = _novRawById[id];
        if (!actual) throw new Error("No se pudo determinar el rango actual de la novedad.");
        // Una novedad con rango abierto necesita que la persona determine el día real de
        // cierre. Si ya tenía fin, `{}` preserva ese límite y el backend verifica coherencia.
        if (actual && !actual.fecha_hasta) {
          var ingresada = window.prompt(
            "Ingresá la fecha de cierre (dd/mm/aaaa):",
            fmtISOtoDMY(todayISO())
          );
          if (ingresada === null) return false;
          var fechaCierre = parseFecha(ingresada);
          if (!fechaCierre) {
            showToast("Ingresá una fecha de cierre válida (dd/mm/aaaa).", "error");
            return false;
          }
          if (actual.fecha_desde && fechaCierre < actual.fecha_desde) {
            showToast("La fecha de cierre no puede ser anterior al inicio.", "error");
            return false;
          }
          body.fecha_hasta = fechaCierre;
        }
      }
      await jsend("POST", "/novedades/" + id + "/" + accion + "/", body);
      var txt = {
        tomar: "tomada",
        aprobar: "aprobada",
        rechazar: "rechazada",
        cerrar: "cerrada",
        anular: "anulada",
      }[accion] || accion;
      showToast("Novedad " + txt, "ok");
      return true;
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
        poblarSelectEmpleados(empEl, n.empleado);
        empEl.disabled = true;
        empEl.style.opacity = ".65";
        empEl.style.cursor = "not-allowed";
      }
      // El PATCH de novedad no toca el estado (lo mueven las acciones explícitas desde el
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
      var payload = {
        nombre: g("nombre"), apellido: g("apellido"),
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
        var rawEdit = _rawEmpleados.find(function (e) {
          return Number(e.id) === Number(editId);
        });
        var relEdit = rawEdit && (rawEdit.relaciones || []).find(function (r) {
          return r.estado === "ACTIVA";
        });
        var sobre = { empleado: payload };
        if (relEdit) {
          var sectorEdit = _sectorByName[g("sector")];
          if (!sectorEdit) throw new Error("Seleccioná el sector");
          sobre.relacion = {
            sector: sectorEdit,
            puesto: puestoSeleccionado(sectorEdit, g("puesto")),
            jornada_legal: JORNADA[g("jornada legal")] || "",
          };
        }
        await jsend("PATCH", "/empleados/" + editId + "/ficha/", sobre);
        showToast("Empleado actualizado", "ok");
        return;
      }
      // Alta completa: empleado + relación ACTIVA.
      if (!payload.nombre || !payload.apellido || !g("dni")) {
        throw new Error("Nombre, apellido y DNI son obligatorios");
      }
      var empresaId = _empresaByName[g("empresa")];
      if (!empresaId) throw new Error("Seleccioná la empresa");   // define en qué empresa corre la jornada
      var sectorId = _sectorByName[g("sector")];
      if (!sectorId) throw new Error("Seleccioná el sector");
      var fechaIng = parseFecha(g("fecha de ingreso"));
      if (!fechaIng) throw new Error("Fecha de ingreso obligatoria (dd/mm/aaaa)");
      var dni = g("dni").replace(/\./g, "");
      var puestoId = puestoSeleccionado(sectorId, g("puesto"));
      var relacion = {
        empresa: empresaId, sector: sectorId,
        puesto: puestoId, fecha_ingreso: fechaIng, jornada_legal: JORNADA[g("jornada legal")] || "",
      };
      if (g("supervisor")) relacion.supervisor = Number(g("supervisor"));
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
      set("nombre", emp.nombre);
      set("apellido", emp.apellido);
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
      // La empresa/sector actual puede estar inactiva: se incluye igual para que se muestre
      // (el campo queda bloqueado en edición, así que no se puede cambiar por otra inactiva).
      poblarSelectEmpresas(f["empresa"], emp.empresa);
      poblarSelectSectores(f["sector"], emp.sector);
      poblarSelectPuestos(f["puesto"], emp._sectorId, emp.puesto);
      poblarSelectSupervisores(f["supervisor"], emp._supervisorId);
      if (f["empresa"] && emp.empresa !== "—") f["empresa"].value = emp.empresa;
      if (f["sector"] && emp.sector !== "—") f["sector"].value = emp.sector;
      if (f["puesto"]) f["puesto"].value = emp.puesto === "—" ? "" : emp.puesto;
      if (f["sector"]) {
        f["sector"].onchange = function () {
          poblarSelectPuestos(f["puesto"], f["sector"].value);
        };
      }
      // Empresa/ingreso/supervisor tienen flujos propios. Sector, puesto y jornada quedan
      // habilitados y se envían en el mismo commit que los datos personales.
      lockCampo(f["empresa"], EMPRESA_LOCK_MSG);
      lockCampo(f["dni"], DNI_LOCK_MSG);
      CAMPOS_RELACION_BLOQUEADOS.forEach(function (k) {
        lockCampo(f[k], RELACION_LOCK_MSG);
      });
      lockCampo(f["estado"], ESTADO_LOCK_MSG);
      notaEdicion(f);
    },

    // Prepara el modal en modo ALTA: habilita empresa y fuerza una elección consciente
    // (opción vacía "Seleccionar empresa…" por defecto), para que la jornada quede bien
    // encuadrada en la empresa correcta y no caiga en la primera por descuido.
    prepareAlta() {
      var f = readAltaForm();
      quitarNotaEdicion();          // el modal es el mismo que el de edición
      // Opciones reales del catálogo (solo activos): reemplazan las hardcodeadas del canvas,
      // así una empresa/sector creado desde Configuración aparece acá sin recargar.
      poblarSelectEmpresas(f["empresa"]);
      poblarSelectSectores(f["sector"]);
      poblarSelectPuestos(f["puesto"], null);
      poblarSelectSupervisores(f["supervisor"], null);
      if (f["sector"]) {
        f["sector"].onchange = function () {
          poblarSelectPuestos(f["puesto"], f["sector"].value);
        };
      }
      unlockEmpresa(f["empresa"]);
      unlockCampo(f["dni"]);
      CAMPOS_RELACION_BLOQUEADOS.forEach(function (k) { unlockCampo(f[k]); });
      ["sector", "puesto", "jornada legal"].forEach(function (k) {
        unlockCampo(f[k]);
      });
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

    // Reingreso: cada dato de la nueva relación se elige de nuevo. La relación anterior queda
    // solo como historial; no es una fuente implícita de empresa, sector ni puesto.
    prepareReingreso() {
      var m = document.querySelector('[data-modal="reingreso"]');
      if (!m) return;
      var empresa = m.querySelector('[data-reingreso="empresa"]');
      var sector = m.querySelector('[data-reingreso="sector"]');
      var puesto = m.querySelector('[data-reingreso="puesto"]');
      var supervisor = m.querySelector('[data-reingreso="supervisor"]');
      poblarSelectEmpresas(empresa);
      poblarSelectSectores(sector);
      [empresa, sector].forEach(function (sel) {
        if (!sel) return;
        var vacia = document.createElement("option");
        vacia.value = "";
        vacia.textContent = sel === empresa ? "Seleccionar empresa…" : "Seleccionar sector…";
        sel.insertBefore(vacia, sel.firstChild);
        sel.value = "";
      });
      poblarSelectPuestos(puesto, null);
      poblarSelectSupervisores(supervisor, null);
      if (sector) sector.onchange = function () {
        poblarSelectPuestos(puesto, sector.value);
      };
    },

    async reingreso(emp) {
      if (!emp) throw new Error("empleado no encontrado");
      var m = document.querySelector('[data-modal="reingreso"]');
      if (!m) throw new Error("modal de reingreso no encontrado");
      var empresaNombre = (m.querySelector('[data-reingreso="empresa"]') || {}).value || "";
      var sectorNombre = (m.querySelector('[data-reingreso="sector"]') || {}).value || "";
      var puestoNombre = (m.querySelector('[data-reingreso="puesto"]') || {}).value || "";
      var supervisorId = (m.querySelector('[data-reingreso="supervisor"]') || {}).value || "";
      var fechaEl = m.querySelector('[data-reingreso="fecha"]');
      var fecha = parseFecha(fechaEl ? fechaEl.value : "");
      var empresaId = _empresaByName[empresaNombre];
      var sectorId = _sectorByName[sectorNombre];
      if (!empresaId) throw new Error("Seleccioná la empresa del reingreso.");
      if (!sectorId) throw new Error("Seleccioná el sector del reingreso.");
      if (!fecha) throw new Error("La fecha de reincorporación es obligatoria.");
      var nueva = {
        empresa: empresaId,
        sector: sectorId,
        puesto: puestoSeleccionado(sectorId, puestoNombre),
        fecha_ingreso: fecha,
      };
      if (supervisorId) nueva.supervisor = Number(supervisorId);
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
      var r = await authedFetch(apiUrl(path), { method: docId ? "PATCH" : "POST", body: fd });
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
    // El cliente común permite tratar sesión vencida y errores de permisos de forma uniforme.
    async descargarDoc(empId, docId) {
      var r = await authedFetch(apiUrl("/empleados/" + empId + "/documentos/" + docId + "/archivo/"), {});
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
      var r = await authedFetch(apiUrl("/empleados/" + empId + "/documentos/" + docId + "/"), { method: "DELETE" });
      if (!r.ok) throw new Error("No se pudo quitar el documento (" + r.status + ")");
      showToast("Documento quitado", "ok");
    },

    // ---------- Foto de perfil del empleado ----------
    // Devuelve un objectURL para poner en <img src>, o null si el empleado no tiene foto.
    // El cliente común permite tratar sesión vencida y errores antes de crear el objectURL.
    async fotoObjectURL(empId) {
      var r = await authedFetch(apiUrl("/empleados/" + empId + "/foto/archivo/"), {});
      if (r.status === 404) return null;         // sin foto cargada: el canvas muestra el avatar por defecto
      if (!r.ok) throw new Error("No se pudo cargar la foto (" + r.status + ")");
      var blob = await r.blob();
      revocarFoto(empId);                        // si había una vieja cacheada, se libera antes de pisarla
      _fotoUrls[empId] = URL.createObjectURL(blob);
      return _fotoUrls[empId];
    },

    // Sube/reemplaza la foto (multipart). El browser arma el boundary; no se fija content-type.
    async subirFoto(empId, file) {
      if (!file) throw new Error("Elegí una imagen.");
      var fd = new FormData();
      fd.append("foto", file);
      var r = await authedFetch(apiUrl("/empleados/" + empId + "/foto/"), { method: "POST", body: fd });
      var data = await r.json().catch(function () { return {}; });
      if (!r.ok) {
        var msg = (data.campos && Object.keys(data.campos).length)
          ? flattenErrs(data.campos).join(" · ")
          : (data.detalle || ("Error " + r.status));
        throw new Error(msg);
      }
      revocarFoto(empId);                        // el objectURL viejo apunta a la imagen anterior
      showToast("Foto actualizada", "ok");
      return data;                               // trae tiene_foto/foto_url ya actualizados
    },

    async quitarFoto(empId) {
      var r = await authedFetch(apiUrl("/empleados/" + empId + "/foto/"), { method: "DELETE" });
      if (!r.ok) throw new Error("No se pudo quitar la foto (" + r.status + ")");
      revocarFoto(empId);
      showToast("Foto quitada", "ok");
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
      var r = await authedFetch(apiUrl("/novedades/" + novId + "/adjuntos/"), {
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
      var r = await authedFetch(apiUrl("/novedades/" + novId + "/adjuntos/" + adjId + "/archivo/"), {});
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
      var r = await authedFetch(apiUrl("/novedades/" + novId + "/adjuntos/" + adjId + "/"), { method: "DELETE" });
      if (!r.ok) throw new Error("No se pudo quitar el respaldo (" + r.status + ")");
      showToast("Respaldo quitado", "ok");
    },
  };
})();
