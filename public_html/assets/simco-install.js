/* "Download for desktop": Chrome/Edge install the site as an app (beforeinstallprompt);
   other browsers, and anyone who wants a file, go to /download for steps and launcher downloads. */
(function () {
  "use strict";
  var deferred = null;
  /* Where desktop install makes no sense: inside the store apps (iOS Capacitor, Android TWA) and on phones.
     The wrappers mark themselves: iOS start URL ?source=ios plus the "SimkoSIApp-iOS" user agent,
     Android TWA start URL ?source=twa plus an android-app:// referrer. The marker is kept for the tab's session. */
  var ua = navigator.userAgent || "";
  var params = new URLSearchParams(window.location.search);
  var src = (params.get("source") || "").toLowerCase();
  var appContext = false;
  try { appContext = sessionStorage.getItem("simkoAppContext") === "1"; } catch (e) {}
  if (!appContext) {
    appContext = !!(window.Capacitor && (typeof window.Capacitor.isNativePlatform === "function" ? window.Capacitor.isNativePlatform() : window.Capacitor.isNative))
      || /SimkoSIApp-/i.test(ua)
      || (document.referrer || "").indexOf("android-app://") === 0
      || src === "twa" || src === "ios" || src === "android";
    if (appContext) { try { sessionStorage.setItem("simkoAppContext", "1"); } catch (e) {} }
  }
  var phone = /iPhone|iPod/.test(ua) || (/Android/.test(ua) && /Mobile/.test(ua))
    || !!(navigator.userAgentData && navigator.userAgentData.mobile);
  var noDesktop = appContext || phone;
  var root = document.documentElement;
  if (appContext) root.classList.add("simko-app-context");
  if (phone) root.classList.add("simko-phone");
  if (noDesktop) {
    root.classList.add("simko-no-desktop");
    var css = document.createElement("style");
    css.textContent = ".simko-no-desktop [data-simko-install], .simko-no-desktop a[href=\"/download\"], .simko-no-desktop .simko-desktop-only { display: none !important; }";
    (document.head || root).appendChild(css);
  }
  function standalone() {
    return (window.matchMedia && (window.matchMedia("(display-mode: standalone)").matches || window.matchMedia("(display-mode: window-controls-overlay)").matches))
      || window.navigator.standalone === true;
  }
  function buttons() { return document.querySelectorAll("[data-simko-install]"); }
  function paint() {
    var installed = standalone();
    buttons().forEach(function (b) {
      if (installed || noDesktop) { b.hidden = true; return; }
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
    if (noDesktop) return Promise.resolve("not-desktop");
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
  window.simkoInstall = { install: install, canPrompt: function () { return !!deferred; }, standalone: standalone,
    appContext: function () { return appContext; }, phone: function () { return phone; } };
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
