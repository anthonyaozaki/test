/*
  main.js
  - Shared JS helpers available to all pages via base.html.
  - Page-specific logic lives in each template's {% block scripts %}.
  -
  - Previously contained dead simulator code (generateData, initLivePage)
  - with syntax errors. That logic now lives entirely in index.html's
  - inline script block, so this file is intentionally minimal.
*/

(function () {
  "use strict";

  // ──── Shared utility: safe setText ────
  window.setText = function (id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  };

  // ──── Shared utility: bucket label ────
  window.bucketLabel = function (count) {
    if (count === 0) return "skip";
    if (count === 1) return "ideal";
    if (count === 2) return "double";
    return "overdrop";
  };
})();