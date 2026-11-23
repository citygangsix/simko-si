/* "Download for desktop": Chrome/Edge install the site as an app (beforeinstallprompt);
   other browsers, and anyone who wants a file, go to /download for steps and launcher downloads. */
(function () {
  "use strict";
  var deferred = null;
  function standalone() {
    return (window.matchMedia && (window.matchMedia("(display-mode: standalone)").matches || window.matchMedia("(display-mode: window-controls-overlay)").matches))
      || window.navigator.standalone === true;
  }
  function buttons() { return document.querySelectorAll("[data-simko-install]"); }
  function paint() {
    var installed = standalone();
    buttons().forEach(function (b) {
      if (installed) { b.hidden = true; return; }
      b.hidden = false;
      b.dataset.ready = deferred ? "1" : "0";
    });
  }
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault();
    deferred = e;
    paint();
  });
  window.addEventListener("appinstalled", function () {
    deferred = null;
    try { localStorage.setItem("simkoInstalled", String(Date.now())); } catch (e) {}
    var note = document.getElementById("installNote");
    if (note) { note.hidden = false; note.textContent = "Simko SI is installed. Open it from your Start menu, Dock, desktop or app list."; }
    paint();
  });
  function install(event) {
    if (event) event.preventDefault();
    if (deferred) {
      var prompt = deferred;
      deferred = null;
      prompt.prompt();
      return prompt.userChoice.then(function (choice) {
        if (choice && choice.outcome !== "accepted") deferred = null;
        paint();
        return choice && choice.outcome;
      });
    }
    if (/^\/download/.test(window.location.pathname)) {
      var hint = document.getElementById("installHint");
      if (hint && hint.scrollIntoView) hint.scrollIntoView({ block: "center" });
      return Promise.resolve("instructions");
    }
    window.location.href = "/download";
    return Promise.resolve("instructions");
  }
  window.simkoInstall = { install: install, canPrompt: function () { return !!deferred; }, standalone: standalone };
  document.addEventListener("click", function (e) {
    var b = e.target && e.target.closest ? e.target.closest("[data-simko-install]") : null;
    if (b) install(e);
  });
  // The tab can turn into the app window without a reload; hide the buttons when that happens.
  if (window.matchMedia) {
    var mq = window.matchMedia("(display-mode: standalone)");
    if (mq.addEventListener) mq.addEventListener("change", paint); else if (mq.addListener) mq.addListener(paint);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", paint); else paint();
})();
