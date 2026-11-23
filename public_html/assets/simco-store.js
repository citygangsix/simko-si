/* Simko SI store-readiness screens (AWAITING JOSEPH'S MOCKUP SIGN-OFF before going live):
   - Delete account (Apple 5.1.1(v), Google Play account deletion policy)
   - Report this reply (Google Play AI-generated content policy)
   Talks to /api/auth (op delete-account) and /api/report. */
(function () {
  function $(id) { return document.getElementById(id); }
  function token() {
    try { return sessionStorage.getItem("podcoderToken") || window.simcoUserToken || ""; }
    catch (e) { return window.simcoUserToken || ""; }
  }
  function post(url, body) {
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ token: token() }, body))
    }).then(function (r) { return r.json().catch(function () { return { ok: false, error: "Something went wrong. Try again." }; }); });
  }
  function open(id) {
    ["accountCard", "deleteAccountCard", "reportCard"].forEach(function (n) { var c = $(n); if (c) c.hidden = n !== id; });
    var s = $("storeStage"); if (s) s.hidden = false;
    var first = $(id) && $(id).querySelector("input, textarea, button:not(.platformClose)");
    if (first) setTimeout(function () { first.focus(); }, 30);
  }
  function close() { var s = $("storeStage"); if (s) s.hidden = true; }

  function bind() {
    var stage = $("storeStage");
    if (!stage || stage.dataset.bound) return;
    stage.dataset.bound = "1";
    stage.addEventListener("click", function (e) { if (e.target === stage) close(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !stage.hidden) close(); });
    Array.prototype.forEach.call(stage.querySelectorAll(".platformClose, [data-store-close]"), function (b) { b.addEventListener("click", close); });

    /* Account card: tap your email at the top */
    var chip = $("accountEmail");
    if (chip) {
      chip.classList.add("is-account-button"); chip.setAttribute("role", "button"); chip.setAttribute("tabindex", "0");
      chip.setAttribute("aria-label", "Account settings");
      var openAccount = function () { $("accountCardEmail").textContent = chip.textContent; open("accountCard"); };
      chip.addEventListener("click", openAccount);
      chip.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openAccount(); } });
    }
    /* Delete account */
    var exp = $("accountExport"), expMsg = $("accountExportMsg");
    if (exp) exp.addEventListener("click", function () {
      exp.disabled = true;
      post("/api/auth", { op: "export-data" }).then(function (d) {
        exp.disabled = false;
        if (!d.ok || !d.export) { expMsg.textContent = d.error || "Could not export right now."; expMsg.hidden = false; return; }
        var blob = new Blob([JSON.stringify(d.export, null, 2)], { type: "application/json" });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "simko-si-data-" + new Date().toISOString().slice(0, 10) + ".json";
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 4000);
        expMsg.textContent = "Your data file is downloading."; expMsg.hidden = false;
      });
    });
    var del = $("accountDelete"), input = $("deleteConfirm"), go = $("deleteAccountGo"), msg = $("deleteAccountMsg");
    if (del) del.addEventListener("click", function () { input.value = ""; go.disabled = true; msg.hidden = true; open("deleteAccountCard"); });
    if (input) input.addEventListener("input", function () { go.disabled = input.value.trim() !== "DELETE"; });
    if (go) go.addEventListener("click", function () {
      go.disabled = true; msg.hidden = false; msg.textContent = "Deleting…";
      post("/api/auth", { op: "delete-account", confirm: input.value.trim() }).then(function (d) {
        if (d && d.ok) {
          msg.textContent = "Your account and chats are deleted. Signing you out…";
          try { sessionStorage.removeItem("podcoderToken"); localStorage.removeItem("simcoSessions"); } catch (e) {}
          setTimeout(function () { location.replace("/"); }, 1800);
        } else {
          msg.textContent = (d && d.error) || "The account could not be deleted. Try again.";
          go.disabled = input.value.trim() !== "DELETE";
        }
      });
    });

    /* Report this reply */
    var form = $("reportForm"), rmsg = $("reportMsg");
    var pending = "";
    function startReport(text) {
      pending = (text || "").trim();
      if (!pending) return;
      form.reset(); rmsg.hidden = true; $("reportSend").disabled = false;
      $("reportQuote").textContent = pending.length > 220 ? pending.slice(0, 220) + "…" : pending;
      open("reportCard");
    }
    var rr = $("replyReport");
    if (rr) rr.addEventListener("click", function () { startReport(($("reply-bubble") || {}).textContent); });
    document.addEventListener("click", function (e) {
      var b = e.target && e.target.closest ? e.target.closest(".bubble .reportReply") : null;
      if (!b) return;
      var bubble = b.closest(".bubble"), clone = bubble.cloneNode(true);
      Array.prototype.forEach.call(clone.querySelectorAll("button"), function (x) { x.remove(); });
      startReport(clone.textContent);
    });
    if (form) form.addEventListener("submit", function (e) {
      e.preventDefault();
      var reason = (form.querySelector("input[name=reportReason]:checked") || {}).value;
      if (!reason) { rmsg.hidden = false; rmsg.textContent = "Pick a reason."; return; }
      $("reportSend").disabled = true; rmsg.hidden = false; rmsg.textContent = "Sending…";
      post("/api/report", { reason: reason, note: $("reportNote").value, reply: pending }).then(function (d) {
        rmsg.textContent = d && d.ok ? "Thanks. The report was sent and the reply will be reviewed." : ((d && d.error) || "The report could not be sent.");
        if (d && d.ok) setTimeout(close, 1600); else $("reportSend").disabled = false;
      });
    });

    /* Show the report flag whenever there is a reply, and add one to earlier replies. */
    var bubble = $("reply-bubble");
    function sync() {
      if (rr) rr.classList.toggle("is-shown", !!(bubble && bubble.textContent.trim()));
      Array.prototype.forEach.call(document.querySelectorAll(".bubble.theirs"), function (b) {
        if (b.querySelector(".reportReply")) return;
        var btn = document.createElement("button");
        btn.type = "button"; btn.className = "reportReply"; btn.setAttribute("aria-label", "Report this reply"); btn.title = "Report this reply";
        btn.innerHTML = FLAG; b.appendChild(btn);
      });
    }
    var queued = false;
    new MutationObserver(function () { if (queued) return; queued = true; requestAnimationFrame(function () { queued = false; sync(); }); }).observe(document.body, { childList: true, subtree: true, characterData: true });
    sync();
  }
  var FLAG = '<svg viewBox="0 0 24 24" width="17" height="17" aria-hidden="true"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22v-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind); else bind();
})();
