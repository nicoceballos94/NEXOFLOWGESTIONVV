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
  function readAltaForm() {
    var m = altaModal();
    if (!m) throw new Error("modal de alta no encontrado");
    var map = {};
    m.querySelectorAll("input,select,textarea").forEach(function (el) {
      var key = normLabel(labelFor(el));
      if (key && map[key] == null) map[key] = el;
    });
    return map;
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
      console.log("[ceibo] catálogos: " + emp.length + " empresas, " + sec.length + " sectores, " + pue.length + " puestos");
    },

    async listEmpleados() {
      _rawEmpleados = await getAllPages("/empleados/?page_size=200");
      var mapped = _rawEmpleados.map(adapt);
      console.log("[ceibo] backend conectado: " + mapped.length + " empleados");
      return mapped;
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
