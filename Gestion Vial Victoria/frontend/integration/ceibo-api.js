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
    USER: "admin",              // login dev único (MVP); se reemplaza por login real
    PASS: "Clave-Segura-123",
  };

  var _token = null;
  var _empresaByName = {}, _empresaById = {};
  var _sectorByName = {}, _sectorById = {};
  var _puestoByName = {}, _puestoById = {};
  var _rawEmpleados = [];
  var _empById = {};              // id → { name, empresa } (para adaptar novedades)
  var _tipoNovByCodigo = {};      // codigo → tipo de novedad (con flags)
  var _novRawById = {};           // id → novedad cruda del backend (para precargar edición)

  // ---------- HTTP ----------
  function auth() { return { Authorization: "Bearer " + _token }; }
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
    var r = await fetch(CONFIG.API + path, { headers: auth() });
    if (!r.ok) throw new Error("GET " + path + " → " + r.status);
    return r.json();
  }
  async function jsend(method, path, body) {
    var r = await fetch(CONFIG.API + path, {
      method: method,
      headers: Object.assign({ "content-type": "application/json" }, auth()),
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
  async function getAllPages(path) {
    var rows = [], url = CONFIG.API + path;
    while (url) {
      var d = await fetch(url, { headers: auth() }).then(function (r) { return r.json(); });
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
  function todayISO() { return new Date().toISOString().slice(0, 10); }
  function splitName(full) {
    var parts = (full || "").trim().split(/\s+/);
    if (parts.length <= 1) return { nombre: parts[0] || "", apellido: "" };
    return { nombre: parts[0], apellido: parts.slice(1).join(" ") };
  }
  function anios(rel) {
    if (!rel || rel.antiguedad_en_dias == null) return "";
    return Math.max(1, Math.floor(rel.antiguedad_en_dias / 365)) + " años";
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

  function docEstado(iso) {
    if (!iso) return "ok";
    var dias = Math.floor((new Date(iso) - new Date()) / 86400000);
    if (dias < 0) return "bad";
    if (dias <= 30) return "warn";
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
      emp: emp.name || n.empleado_nombre || "—",
      empresa: emp.empresa || "—",
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
  function nextLegajo() {
    var max = 0;
    _rawEmpleados.forEach(function (e) {
      var n = parseInt(String(e.legajo).replace(/\D/g, ""), 10);
      if (!isNaN(n) && n > max) max = n;
    });
    return String(max + 1).padStart(4, "0");
  }

  // ---------- form de alta: lectura/escritura por etiqueta ----------
  function altaModal() { return document.querySelector('[data-modal="alta"]'); }
  // Etiqueta de un input: sube por los ancestros hasta el wrapper del campo y toma
  // el primer <div> "de texto" (sin input adentro). Robusto a envolturas extra
  // (p. ej. el input type="date" del diseño tiene un wrapper de calendario).
  function labelFor(el) {
    var node = el;
    for (var i = 0; i < 4 && node; i++) {
      node = node.parentElement;
      if (!node) break;
      var divs = node.querySelectorAll(":scope > div");
      for (var j = 0; j < divs.length; j++) {
        var d = divs[j];
        if (d.querySelector("input,select,textarea")) continue;   // no es la etiqueta
        var txt = d.textContent.trim();
        if (txt && txt.length <= 32) return txt;
      }
    }
    return "";
  }
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

  // ---------- helpers de novedad ----------
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
  window.CeiboAPI = {
    toast: showToast,

    async init() {
      var tk = await fetch(CONFIG.API + "/auth/token/", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ username: CONFIG.USER, password: CONFIG.PASS }),
      }).then(function (r) { return r.json(); });
      if (!tk.access) throw new Error("login falló: " + JSON.stringify(tk));
      _token = tk.access;
      var emp = await getAllPages("/empresas/?page_size=200");
      var sec = await getAllPages("/sectores/?page_size=200");
      var pue = await getAllPages("/puestos/?page_size=200");
      emp.forEach(function (x) { _empresaByName[x.nombre] = x.id; _empresaById[x.id] = x.nombre; });
      sec.forEach(function (x) { _sectorByName[x.nombre] = x.id; _sectorById[x.id] = x.nombre; });
      pue.forEach(function (x) { _puestoByName[x.nombre.toLowerCase()] = x.id; _puestoById[x.id] = x.nombre; });
      var tipos = await getAllPages("/tipos-novedad/?page_size=200");
      tipos.forEach(function (t) { _tipoNovByCodigo[t.codigo] = t; });
      console.log("[ceibo] catálogos: " + emp.length + " empresas, " + sec.length + " sectores, " + pue.length + " puestos, " + tipos.length + " tipos de novedad");
    },

    async listEmpleados() {
      _rawEmpleados = await getAllPages("/empleados/?page_size=200");
      var mapped = _rawEmpleados.map(adapt);
      _empById = {};
      mapped.forEach(function (m) { _empById[m.id] = { name: m.name, empresa: m.empresa }; });
      console.log("[ceibo] backend conectado: " + mapped.length + " empleados");
      return mapped;
    },

    // Novedades con cadenas expandidas: se agrupan las prórrogas bajo su madre
    // (novedad_origen) para tener la cadena completa sin N+1.
    async listNovedades() {
      var raw = await getAllPages("/novedades/?expandir_cadenas=true&page_size=200");
      _novRawById = {};
      raw.forEach(function (n) { _novRawById[n.id] = n; });
      var madres = raw.filter(function (n) { return !n.novedad_origen; });
      var rows = madres.map(function (m) {
        var out = adaptNov(m);
        var pros = raw.filter(function (n) { return n.novedad_origen === m.id; })
          .sort(function (a, b) { return a.fecha_desde < b.fecha_desde ? -1 : 1; });
        out.prorrogas = pros.map(function (p) {
          return {
            desde: fmtISOtoDMY(p.fecha_desde), hasta: fmtISOtoDMY(p.fecha_hasta),
            motivo: p.motivo || "", estado: p.estado_display,
            cert: !!p.certificado_recibido_en,
          };
        });
        if (pros.length) {
          out.madreDesde = fmtISOtoDMY(m.fecha_desde);
          out.madreHasta = fmtISOtoDMY(m.fecha_hasta);
          out.madreMotivo = m.motivo || m.tipo_novedad_nombre;
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
        dl.innerHTML = _rawEmpleados.map(function (e) {
          return '<option value="' + (e.nombre + " " + e.apellido).trim() + '"></option>';
        }).join("");
        empEl.parentNode.replaceChild(input, empEl);
        input.parentNode.appendChild(dl);
      }
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
      var codigo = TIPONOV[g("tipo")] || "";
      var tipo = _tipoNovByCodigo[codigo];
      if (!tipo) throw new Error("Tipo de novedad inválido");
      var desde = parseFecha(g("fecha"));
      if (!desde) throw new Error("Fecha obligatoria (dd/mm/aaaa)");
      var payload = {
        tipo_novedad: tipo.id, fecha_desde: desde,
        motivo: g("motivo"), observaciones: g("observaciones"),
      };
      // Días → fecha_hasta (el PATCH de edición no acepta 'dias', así que mandamos el rango).
      var dias = g("dias"); if (dias) payload.fecha_hasta = addDaysISO(desde, Number(dias) - 1);
      var aviso = parseFecha(g("fecha aviso del empleado")); if (aviso) payload.fecha_aviso_empleado = aviso;
      var clasif = CLASIF[g("clasificacion")]; if (clasif) payload.clasificacion = clasif;
      if (codigo === "HORAS_EXTRA") {
        var h = g("cantidad de horas");
        if (!h) throw new Error("Cantidad de horas obligatoria");
        payload.cantidad_horas = h;
      } else {
        // El bloque de praxis se muestra cuando el toggle está activo: si sus inputs existen,
        // la novedad requiere praxis y se envían las fechas cargadas.
        var praxisFields = ["fecha turno praxis", "fecha fin estimada", "fecha reintegro", "fecha certificado recibido"];
        var apiKeys = ["fecha_turno_praxis", "fecha_fin_estimada", "fecha_reintegro", "certificado_recibido_en"];
        if (f["fecha turno praxis"]) payload.requiere_praxis = true;
        praxisFields.forEach(function (lbl, i) { var v = parseFecha(g(lbl)); if (v) payload[apiKeys[i]] = v; });
      }
      if (editNovId) {
        await jsend("PATCH", "/novedades/" + editNovId + "/", payload);  // empleado/estado no se tocan
        showToast("Novedad actualizada", "ok");
        return;
      }
      var empEl = f["empleado"];
      var empId = empEl && empEl.tagName === "SELECT" ? empEl.value : empIdByName(g("empleado"));
      if (!empId) throw new Error("Empleado inválido: elegí un nombre de la lista de registrados");
      payload.empleado = Number(empId);
      var nov = await jsend("POST", "/novedades/", payload);
      var accion = ESTADONOV[g("estado")];
      if (accion) await jsend("POST", "/novedades/" + nov.id + "/" + accion + "/", {});
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
        ro.value = (_empById[n.empleado] && _empById[n.empleado].name) || n.empleado_nombre || "";
        ro.disabled = true;
        ro.style.cssText = empEl.style.cssText + ";opacity:.65;cursor:not-allowed";
        empEl.parentNode.replaceChild(ro, empEl);
      }
      set("fecha", n.fecha_desde);
      if (f["motivo"]) f["motivo"].value = n.motivo || "";
      if (f["observaciones"]) f["observaciones"].value = n.observaciones || "";
      if (f["clasificacion"]) f["clasificacion"].value = CLASIF_REV[n.clasificacion] || "";
      if (f["dias"] && n.fecha_hasta) f["dias"].value = String(diasEntreISO(n.fecha_desde, n.fecha_hasta));
      if (f["cantidad de horas"] && n.cantidad_horas != null) f["cantidad de horas"].value = String(Number(n.cantidad_horas));
      set("fecha aviso del empleado", n.fecha_aviso_empleado);
      set("fecha turno praxis", n.fecha_turno_praxis);
      set("fecha fin estimada", n.fecha_fin_estimada);
      set("fecha reintegro", n.fecha_reintegro);
      set("fecha certificado recibido", n.certificado_recibido_en);
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
    async submitAlta(editId) {
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
      var fechaIng = parseFecha(g("fecha de ingreso"));
      if (!fechaIng) throw new Error("Fecha de ingreso obligatoria (dd/mm/aaaa)");
      payload.dni = g("dni").replace(/\./g, "");
      payload.legajo = nextLegajo();
      var puestoId = await getOrCreatePuesto(g("puesto"));
      payload.relacion = {
        empresa: _empresaByName[g("empresa")], sector: _sectorByName[g("sector")],
        puesto: puestoId, fecha_ingreso: fechaIng, jornada_legal: JORNADA[g("jornada legal")] || "",
      };
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
    },

    // Baja lógica: motivo del modal de baja, finaliza la relación ACTIVA (fecha = hoy).
    async darDeBaja(emp) {
      if (!emp || !emp._relacionActivaId) throw new Error("el empleado no tiene relación activa");
      var m = document.querySelector('[data-modal="baja"]');
      var sel = m ? m.querySelector("select") : null;
      var motivo = MOTIVO[sel ? sel.value : "Renuncia"] || "RENUNCIA";
      await jsend("POST", "/empleados/" + emp.id + "/relaciones/" + emp._relacionActivaId + "/finalizar/", {
        fecha_egreso: todayISO(), motivo_egreso: motivo,
      });
      showToast("Baja registrada", "ok");
    },

    // Reingreso: nueva relación ACTIVA (misma empresa de la última relación, fecha = hoy).
    async reingreso(emp) {
      if (!emp) throw new Error("empleado no encontrado");
      if (!emp._empresaId) throw new Error("no hay empresa de referencia para el reingreso");
      await jsend("POST", "/empleados/" + emp.id + "/relaciones/", {
        empresa: emp._empresaId, fecha_ingreso: todayISO(),
      });
      showToast("Reingreso registrado", "ok");
    },

    // Documentos de un empleado (lectura) → shape del diseño.
    async loadDocs(id) {
      var docs = await jget("/empleados/" + id + "/documentos/");
      return (docs || []).map(function (d) {
        return {
          tipo: d.tipo_documento_nombre || ("Documento #" + d.tipo_documento),
          fecha: d.fecha_vencimiento ? "Vence " + fmtISOtoDMY(d.fecha_vencimiento) : "Sin vencimiento",
          estado: docEstado(d.fecha_vencimiento),
        };
      });
    },
  };
})();
