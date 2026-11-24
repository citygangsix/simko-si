/* Simko SI account security: two-step sign-in (authenticator app + backup codes) and signed-in devices.
   Talks to /api/auth ops twofa-status, twofa-setup, twofa-enable, twofa-disable, devices,
   device-signout, devices-signout-others. The QR code is drawn here (assets/qrcode.js); nothing leaves the site. */
(function () {
  function $(id) { return document.getElementById(id); }
  function token() {
    try { return sessionStorage.getItem("podcoderToken") || window.simcoUserToken || ""; }
    catch (e) { return window.simcoUserToken || ""; }
  }
  function post(body) {
    return fetch("/api/auth", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ token: token() }, body))
    }).then(function (r) { return r.json().catch(function () { return { ok: false, error: "Something went wrong. Try again." }; }); })
      .catch(function () { return { ok: false, error: "No connection. Try again." }; });
  }
  function open(id) {
    var stage = $("storeStage");
    Array.prototype.forEach.call(stage.querySelectorAll(":scope > section"), function (c) { c.hidden = c.id !== id; });
    stage.hidden = false;
  }
  var qrLoading = null;
  function loadQr() {
    if (window.qrcode) return Promise.resolve();
    if (qrLoading) return qrLoading;
    qrLoading = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = "/assets/qrcode.js?v=2.0.4"; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
    return qrLoading;
  }
  function when(ts) {
    if (!ts) return "before this list existed";
    try { return new Date(ts * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }); }
    catch (e) { return ""; }
  }
  function ago(ts) {
    if (!ts) return "unknown";
    var s = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    return when(ts);
  }

  /* ---------- two-step sign-in ---------- */
  function twofaMsg(t) { $("twofaMsg").textContent = t || ""; }
  function paintTwofa(st) {
    var on = !!(st && st.enabled);
    $("twofaStatus").textContent = on
      ? "On. " + st.backup_codes_left + " of 8 backup codes left."
      : "Off. Only your password protects this account.";
    $("twofaStart").hidden = on;
    $("twofaOffStart").hidden = !on;
    $("twofaSetup").hidden = true;
    $("twofaOff").hidden = true;
  }
  function openTwofa() {
    twofaMsg(""); $("twofaCodes").hidden = true;
    open("twofaCard");
    $("twofaStatus").textContent = "Checking…";
    post({ op: "twofa-status" }).then(function (d) {
      if (!d.ok) { twofaMsg(d.error || "Could not load this. Sign in again."); return; }
      paintTwofa(d);
    });
  }
  function startSetup() {
    var btn = $("twofaStart"); btn.disabled = true; twofaMsg("");
    Promise.all([post({ op: "twofa-setup" }), loadQr().catch(function () {})]).then(function (r) {
      var d = r[0]; btn.disabled = false;
      if (!d.ok) { twofaMsg(d.error || "Could not start. Try again."); return; }
      $("twofaSecret").textContent = d.secret.replace(/(.{4})/g, "$1 ").trim();
      var box = $("twofaQr"); box.replaceChildren();
      if (window.qrcode) {
        var qr = window.qrcode(0, "M"); qr.addData(d.otpauth); qr.make();
        box.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
      } else {
        box.textContent = "Type the key below into your app.";
      }
      box.dataset.uri = d.otpauth;
      btn.hidden = true;
      $("twofaSetup").hidden = false;
      $("twofaSetupCode").value = "";
      $("twofaSetupCode").focus();
    });
  }
  function confirmSetup() {
    var code = $("twofaSetupCode").value.replace(/\s/g, "");
    if (!/^\d{6}$/.test(code)) { twofaMsg("Type the 6 digits your app shows."); return; }
    var btn = $("twofaConfirm"); btn.disabled = true; twofaMsg("Checking…");
    post({ op: "twofa-enable", code: code }).then(function (d) {
      btn.disabled = false;
      if (!d.ok) { twofaMsg(d.error || "That code did not match."); return; }
      twofaMsg("Two-step sign-in is on.");
      paintTwofa(d);
      var list = $("twofaCodeList"); list.replaceChildren();
      (d.backup_codes || []).forEach(function (c) { var li = document.createElement("li"); li.textContent = c; list.appendChild(li); });
      $("twofaCodes").hidden = false;
      $("twofaOffStart").hidden = true;
      $("twofaCodesDone").focus();
    });
  }
  function copyCodes() {
    var text = Array.prototype.map.call($("twofaCodeList").children, function (li) { return li.textContent; }).join("\n");
    var done = function () { twofaMsg("Backup codes copied."); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { twofaMsg("Copy did not work. Write them down."); });
    else twofaMsg("Copy did not work. Write them down.");
  }
  function turnOff() {
    var btn = $("twofaOffGo");
    var pw = $("twofaOffPassword").value, code = $("twofaOffCode").value.trim();
    if (!pw || !code) { twofaMsg("Type your password and a code."); return; }
    btn.disabled = true; twofaMsg("Checking…");
    post({ op: "twofa-disable", password: pw, code: code }).then(function (d) {
      btn.disabled = false;
      if (!d.ok) { twofaMsg(d.error || "The password or code did not match."); return; }
      $("twofaOffPassword").value = ""; $("twofaOffCode").value = "";
      paintTwofa(d);
      twofaMsg("Two-step sign-in is off.");
    });
  }

  /* ---------- devices ---------- */
  function devicesMsg(t) { $("devicesMsg").textContent = t || ""; }
  function paintDevices(rows) {
    var list = $("deviceList"); list.replaceChildren();
    rows = rows || [];
    rows.forEach(function (row) {
      var li = document.createElement("li");
      if (row.current) li.className = "is-current";
      var text = document.createElement("span"); text.className = "deviceText";
      text.appendChild(document.createTextNode(row.browser + " on " + row.os));
      if (row.current) { var here = document.createElement("span"); here.className = "deviceHere"; here.textContent = "This device"; text.appendChild(here); }
      var meta = document.createElement("span"); meta.className = "deviceMeta";
      meta.textContent = "IP " + row.ip + " · Signed in " + when(row.created_at) + " · Last active " + (row.current ? "now" : ago(row.last_seen));
      text.appendChild(meta);
      li.appendChild(text);
      if (!row.current) {
        var b = document.createElement("button"); b.type = "button"; b.className = "deviceSignOut";
        b.textContent = "Sign out"; b.setAttribute("aria-label", "Sign out " + row.browser + " on " + row.os);
        b.addEventListener("click", function () {
          b.disabled = true;
          post({ op: "device-signout", device_id: row.id }).then(function (d) {
            if (!d.ok) { b.disabled = false; devicesMsg(d.error || "Could not sign that device out."); return; }
            paintDevices(d.devices); devicesMsg(row.browser + " on " + row.os + " is signed out.");
          });
        });
        li.appendChild(b);
      }
      list.appendChild(li);
    });
    $("devicesSignOutOthers").hidden = rows.filter(function (r) { return !r.current; }).length === 0;
  }
  function openDevices() {
    devicesMsg(""); open("devicesCard");
    post({ op: "devices" }).then(function (d) {
      if (!d.ok) { devicesMsg(d.error || "Could not load devices. Sign in again."); return; }
      paintDevices(d.devices);
    });
  }
  function signOutOthers() {
    var b = $("devicesSignOutOthers"); b.disabled = true;
    post({ op: "devices-signout-others" }).then(function (d) {
      b.disabled = false;
      if (!d.ok) { devicesMsg(d.error || "Could not sign the others out."); return; }
      paintDevices(d.devices);
      devicesMsg(d.signed_out === 1 ? "1 other device is signed out." : d.signed_out + " other devices are signed out.");
    });
  }

  function bind() {
    if (!$("twofaCard") || $("twofaCard").dataset.bound) return;
    $("twofaCard").dataset.bound = "1";
    $("accountTwofa").addEventListener("click", openTwofa);
    $("accountDevices").addEventListener("click", openDevices);
    $("twofaStart").addEventListener("click", startSetup);
    $("twofaConfirm").addEventListener("click", confirmSetup);
    $("twofaSetupCode").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); confirmSetup(); } });
    $("twofaCodesCopy").addEventListener("click", copyCodes);
    $("twofaCodesDone").addEventListener("click", function () { $("twofaCodes").hidden = true; $("twofaCodeList").replaceChildren(); $("twofaOffStart").hidden = false; twofaMsg(""); });
    $("twofaOffStart").addEventListener("click", function () { $("twofaOffStart").hidden = true; $("twofaOff").hidden = false; twofaMsg(""); $("twofaOffPassword").focus(); });
    $("twofaOffCancel").addEventListener("click", function () { $("twofaOff").hidden = true; $("twofaOffStart").hidden = false; twofaMsg(""); });
    $("twofaOffGo").addEventListener("click", turnOff);
    $("twofaOffCode").addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); turnOff(); } });
    $("devicesSignOutOthers").addEventListener("click", signOutOthers);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind); else bind();
})();
