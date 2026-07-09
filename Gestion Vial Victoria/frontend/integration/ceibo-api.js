/* ============================================================================
 * Ceibo · Capa de integración con el backend Django (Gestión RRHH)
 * ----------------------------------------------------------------------------
 * Esta capa es lo ÚNICO que se escribe a mano. El diseño (design/*.dc.html) se
 * baja de Claude Design y NO se edita; build.py le inyecta shims delgados que
 * llaman a `window.CeiboAPI.*` (definido acá). Así un rediseño se re-cablea solo.
 *
 * Expone window.CeiboAPI con: init, listEmpleados, submitAlta, darDeBaja,
 * reingreso, loadDocs, prefillAlta.
 * ==========================================================================*/
(function () {
  "use strict";

  var CONFIG = {
    API: "http://localhost:8000/api/v1",
    // Login dev único (MVP). Se reemplaza por login real por usuario más adelante.
    USER: "admin",
    PASS: "Clave-Segura-123",
  };

  var _token = null;
  var _empresaByName = {}, _empresaById = {};
  var _sectorByName = {}, _sectorById = {};
  var _puestoByName = {}, _puestoById = {};
  var _rawEmpleados = [];

  // ---------- helpers HTTP ----------
  function auth() { return { Authorization: "Bearer " + _token }; }

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
      var msg = data.detalle || JSON.stringify(data.campos || data);
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

  // ---------- helpers de formato ----------
  function fmtISOtoDMY(iso) { return iso ? iso.split("-").reverse().join("/") : ""; }
  function parseDMYtoISO(s) {
    if (!s) return null;
    var p = s.trim().split(/[\/\-]/);
    if (p.length !== 3) return null;
    var d = p[0].padStart(2, "0"), m = p[1].padStart(2, "0"), y = p[2];
    if (y.length !== 4) return null;
    return y + "-" + m + "-" + d;
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
  var MOTIVO = {
    "Renuncia": "RENUNCIA", "Fin de contrato": "FIN_CONTRATO", "Despido": "DESPIDO",
    "Mudanza": "MUDANZA", "Jubilación": "JUBILACION", "Jubilacion": "JUBILACION",
  };
  function docEstado(iso) {
    if (!iso) return "ok";
    var dias = Math.floor((new Date(iso) - new Date()) / 86400000);
    if (dias < 0) return "bad";
    if (dias <= 30) return "warn";
    return "ok";
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
      domicilio: e.direccion || "", cuil: e.cuil || "", historial: historial, docs: [],
      // metadatos para el cableado (no los usa el template):
      _relacionActivaId: activa.id || null, _empresaId: activa.empresa || null,
    };
  }

  // ---------- catálogos: get-or-create de puesto ----------
  async function getOrCreatePuesto(nombre) {
    nombre = (nombre || "").trim();
    if (!nombre) return null;
    if (_puestoByName[nombre.toLowerCase()]) return _puestoByName[nombre.toLowerCase()];
    var p = await jsend("POST", "/puestos/", { nombre: nombre });
    _puestoByName[nombre.toLowerCase()] = p.id; _puestoById[p.id] = p.nombre;
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

  // ---------- DOM de los modales (inputs sin binding → se leen del DOM) ----------
  function altaModal() { return document.querySelector('[data-modal="alta"]'); }
  function readAltaForm() {
    var m = altaModal();
    if (!m) throw new Error("modal de alta no encontrado");
    var inp = m.querySelectorAll("input");   // [name, dni, fecha, puesto, email, tel]
    var sel = m.querySelectorAll("select");  // [empresa, sector]
    return {
      nombreApellido: inp[0] ? inp[0].value : "",
      dni: inp[1] ? inp[1].value.replace(/\./g, "").trim() : "",
      fecha: inp[2] ? inp[2].value : "",
      puesto: inp[3] ? inp[3].value : "",
      email: inp[4] ? inp[4].value : "",
      tel: inp[5] ? inp[5].value : "",
      empresa: sel[0] ? sel[0].value : "",
      sector: sel[1] ? sel[1].value : "",
    };
  }

  // ============================ API pública ============================
  window.CeiboAPI = {
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

    // Alta (editId=null) o edición (editId=id). Lee el form del DOM.
    async submitAlta(editId, selEmp) {
      var f = readAltaForm();
      var nm = splitName(f.nombreApellido);
      if (editId) {
        // Edición: solo campos de la persona (empresa/sector/puesto/fecha = relación, aparte).
        await jsend("PATCH", "/empleados/" + editId + "/", {
          nombre: nm.nombre, apellido: nm.apellido, email: f.email, telefono: f.tel,
        });
        return;
      }
      // Alta completa: empleado + relación ACTIVA.
      if (!nm.nombre || !f.dni) throw new Error("Nombre y DNI son obligatorios");
      var fechaISO = parseDMYtoISO(f.fecha);
      if (!fechaISO) throw new Error("Fecha de ingreso inválida (usá dd/mm/aaaa)");
      var puestoId = await getOrCreatePuesto(f.puesto);
      await jsend("POST", "/empleados/", {
        legajo: nextLegajo(), dni: f.dni, nombre: nm.nombre, apellido: nm.apellido,
        email: f.email, telefono: f.tel,
        relacion: {
          empresa: _empresaByName[f.empresa], sector: _sectorByName[f.sector],
          puesto: puestoId, fecha_ingreso: fechaISO,
        },
      });
    },

    // Baja lógica: lee el motivo del modal, finaliza la relación ACTIVA (fecha = hoy).
    async darDeBaja(emp) {
      if (!emp || !emp._relacionActivaId) throw new Error("el empleado no tiene relación activa");
      var m = document.querySelector('[data-modal="baja"]');
      var sel = m ? m.querySelector("select") : null;
      var motivo = MOTIVO[sel ? sel.value : "Renuncia"] || "RENUNCIA";
      await jsend("POST", "/empleados/" + emp.id + "/relaciones/" + emp._relacionActivaId + "/finalizar/", {
        fecha_egreso: todayISO(), motivo_egreso: motivo,
      });
    },

    // Reingreso: nueva relación ACTIVA (misma empresa de la última relación, fecha = hoy).
    async reingreso(emp) {
      if (!emp) throw new Error("empleado no encontrado");
      var empresaId = emp._empresaId;
      if (!empresaId) throw new Error("no hay empresa de referencia para el reingreso");
      await jsend("POST", "/empleados/" + emp.id + "/relaciones/", {
        empresa: empresaId, fecha_ingreso: todayISO(),
      });
    },

    // Documentos de un empleado (lectura) → shape del diseño.
    async loadDocs(id) {
      var docs = await jget("/empleados/" + id + "/documentos/");
      return (docs || []).map(function (d) {
        var est = docEstado(d.fecha_vencimiento);
        return {
          tipo: d.tipo_documento_nombre || ("Documento #" + d.tipo_documento),
          fecha: d.fecha_vencimiento ? "Vence " + fmtISOtoDMY(d.fecha_vencimiento) : "Sin vencimiento",
          estado: est,
        };
      });
    },

    // Prefill del modal de alta cuando se abre en modo edición.
    prefillAlta(emp) {
      var m = altaModal();
      if (!m || !emp) return;
      var inp = m.querySelectorAll("input");
      var sel = m.querySelectorAll("select");
      if (inp[0]) inp[0].value = emp.name;
      if (inp[1]) inp[1].value = emp.dni;
      if (inp[2]) inp[2].value = emp.ingreso;
      if (inp[3]) inp[3].value = emp.puesto === "—" ? "" : emp.puesto;
      if (inp[4]) inp[4].value = emp.email;
      if (inp[5]) inp[5].value = emp.tel;
      if (sel[0] && emp.empresa !== "—") sel[0].value = emp.empresa;
      if (sel[1] && emp.sector !== "—") sel[1].value = emp.sector;
    },
  };
})();
