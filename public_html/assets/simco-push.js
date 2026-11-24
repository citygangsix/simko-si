/* Simko SI alerts: Web Push for routines. The toggle lives in the Routines card.
   Uses the browser's own free push service; keys come from /api/platform op push-status. */
(function () {
  function $(id) { return document.getElementById(id); }
  function token() {
    try { return sessionStorage.getItem("podcoderToken") || window.simcoUserToken || ""; }
    catch (e) { return window.simcoUserToken || ""; }
  }
  function post(body) {
    return fetch("/api/platform", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ token: token() }, body))
    }).then(function (r) { return r.json().catch(function () { return { ok: false, error: "Something went wrong." }; }); })
      .catch(function () { return { ok: false, error: "No connection. Try again." }; });
  }
  function msg(t) { var m = $("pushMsg"); if (m) m.textContent = t || ""; }
  function supported() { return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window; }
  function keyBytes(b64u) {
    var s = b64u.replace(/-/g, "+").replace(/_/g, "/"); while (s.length % 4) s += "=";
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  var status = null;
  function registration() {
    return navigator.serviceWorker.getRegistration("/").then(function (r) { return r || navigator.serviceWorker.register("/sw.js", { scope: "/" }); })
      .then(function () { return navigator.serviceWorker.ready; });
  }
  function currentSub() {
    if (!supported()) return Promise.resolve(null);
    return registration().then(function (reg) { return reg.pushManager.getSubscription(); }).catch(function () { return null; });
  }
  function paint() {
    var box = $("pushBox"); if (!box) return;
    if (!status || !status.available) { box.hidden = true; return; }
    box.hidden = false;
    if (!supported()) { $("pushRoutineToggle").disabled = true; msg("This browser can't show alerts. On iPhone, add Simko SI to your Home Screen first."); return; }
    currentSub().then(function (sub) {
      var on = !!(status.routine_alerts && sub && Notification.permission === "granted");
      $("pushRoutineToggle").checked = on;
      $("pushTest").hidden = !sub || Notification.permission !== "granted";
      if (Notification.permission === "denied") msg("Alerts are blocked for this site in your browser settings.");
    });
  }
  function refresh() {
    if (!token() && document.documentElement.getAttribute("data-simko-signed") !== "1") return;
    post({ op: "push-status" }).then(function (d) { if (d && d.ok) { status = d; paint(); } });
  }
  function turnOn() {
    var t = $("pushRoutineToggle");
    t.disabled = true; msg("Asking your browser…");
    Notification.requestPermission().then(function (perm) {
      if (perm !== "granted") throw new Error(perm === "denied" ? "Alerts are blocked. Allow notifications for simkosi.com in your browser settings." : "Alerts were not allowed.");
      return registration();
    }).then(function (reg) {
      return reg.pushManager.getSubscription().then(function (sub) {
        return sub || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(status.public_key) });
      });
    }).then(function (sub) {
      return post({ op: "push-subscribe", subscription: sub.toJSON(), routine_alerts: true });
    }).then(function (d) {
      t.disabled = false;
      if (!d.ok) { t.checked = false; msg(d.error || "Could not turn alerts on."); return; }
      status = d; msg("Alerts are on for this device."); paint();
    }).catch(function (e) { t.disabled = false; t.checked = false; msg((e && e.message) || "Could not turn alerts on."); });
  }
  function turnOff() {
    var t = $("pushRoutineToggle"); t.disabled = true;
    post({ op: "push-pref", routine_alerts: false }).then(function (d) {
      t.disabled = false;
      if (d && d.ok) { status = d; msg("Routine alerts are off."); paint(); } else { t.checked = true; msg((d && d.error) || "Could not turn alerts off."); }
    });
  }
  function sendTest() {
    var b = $("pushTest"); b.disabled = true; msg("Sending…");
    post({ op: "push-test" }).then(function (d) {
      b.disabled = false;
      if (!d.ok) { msg(d.error || "The test alert was not sent."); return; }
      msg(d.sent > 0 ? "Test alert sent. It should pop up in a few seconds." : "The push service did not accept the alert. Turn alerts off and on again.");
    });
  }
  function bind() {
    var t = $("pushRoutineToggle");
    if (!t || t.dataset.bound) return;
    t.dataset.bound = "1";
    t.addEventListener("change", function () { if (t.checked) turnOn(); else turnOff(); });
    $("pushTest").addEventListener("click", sendTest);
    var open = $("routineOpen");
    if (open) open.addEventListener("click", function () { setTimeout(refresh, 50); });
    if (supported()) navigator.serviceWorker.addEventListener("message", function (e) {
      if (e.data && e.data.type === "simko-push") { msg("Alert received: " + e.data.body); window.dispatchEvent(new CustomEvent("simko-push", { detail: e.data })); }
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind); else bind();
})();
