/* Aplica el tema antes del primer render sin requerir JavaScript inline. */
(function () {
  "use strict";
  try {
    var tema = localStorage.getItem("ceibo-th") || "light";
    document.documentElement.setAttribute("data-th", tema);
    var meta = document.getElementsByName("theme-color")[0];
    if (meta) meta.setAttribute("content", tema === "dark" ? "#0A1120" : "#EEF2F7");
  } catch (e) {
    // El almacenamiento puede estar bloqueado; el tema claro del documento es seguro.
  }
})();
