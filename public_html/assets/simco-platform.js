/* Extra Simko SI screens. Loaded only when a platform flag is on. */
(function () {
  function $(id) { return document.getElementById(id); }
  function flags() { return window.simkoPlatformFlags || {}; }
  function token() {
    try { return sessionStorage.getItem("podcoderToken") || window.simcoUserToken || ""; }
    catch (e) { return window.simcoUserToken || ""; }
  }
  function signedIn() {
    return document.documentElement.getAttribute("data-simko-signed") === "1" || !!token();
  }
  function post(body) {
    return fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ token: token() }, body))
    }).then(function (res) { return res.json(); });
  }
  function show(id) {
    ["paywallCard", "usagePage", "approvalCard", "searchCard", "memoryCard", "routineCard", "imageCard", "shareCard", "oauthCard", "vaultCard", "connectorCard"].forEach(function (name) {
      var card = $(name);
      if (card) card.hidden = name !== id;
    });
    var stage = $("platformStage");
    if (stage) stage.hidden = false;
  }
  function hide() {
    var stage = $("platformStage");
    if (stage) stage.hidden = true;
  }
  function showPaywall(data) {
    var lead = $("paywallLead");
    if (lead) {
      var used = data && data.used != null ? data.used : 5;
      lead.textContent = used + " messages are used. Nothing is charged until you tap pay.";
    }
    var note = $("paywallNote");
    if (note) note.textContent = "";
    show("paywallCard");
  }
  function paintUsage(data) {
    var summary = $("usageSummary");
    var list = $("usageList");
    if (summary) {
      if (data.status === "paid") summary.textContent = "This month is paid. " + data.used + " messages so far.";
      else summary.textContent = data.used + " of " + data.limit + " messages used. " + data.remaining + " left.";
    }
    if (!list) return;
    list.replaceChildren();
    (data.events || []).forEach(function (event) {
      var item = document.createElement("li");
      var when = new Date((event.created_at || 0) * 1000);
      item.textContent = (event.kind === "voice" ? "Voice turn" : "Message") + " · " + when.toLocaleString();
      list.appendChild(item);
    });
    if (!(data.events || []).length) {
      var empty = document.createElement("li");
      empty.textContent = "No messages yet.";
      list.appendChild(empty);
    }
  }
  var pendingApproval = null;
  function paintAudit(rows) {
    var list = $("auditList");
    if (!list) return;
    list.replaceChildren();
    (rows || []).forEach(function (row) {
      var item = document.createElement("li");
      item.textContent = row.summary;
      list.appendChild(item);
    });
    if (!(rows || []).length) {
      var empty = document.createElement("li");
      empty.textContent = "Nothing has been approved or declined yet.";
      list.appendChild(empty);
    }
  }
  function showApproval(approval, retry) {
    pendingApproval = { approval: approval, retry: retry };
    var summary = $("approvalSummary");
    if (summary) summary.textContent = approval.summary || "Simko SI is waiting for you.";
    post({ op: "audit" }).then(function (data) { paintAudit(data.audit || []); });
    show("approvalCard");
  }
  function showSources(sources) {
    var list = $("searchSources");
    if (!list) return;
    list.replaceChildren();
    (sources || []).forEach(function (url) {
      var item = document.createElement("li");
      var link = document.createElement("a");
      link.href = url;
      link.textContent = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.appendChild(link);
      list.appendChild(item);
    });
    if (!(sources || []).length) {
      var empty = document.createElement("li");
      empty.textContent = "No safe sources came back.";
      list.appendChild(empty);
    }
    show("searchCard");
  }
  function boot() {
    var searchClose = $("searchClose");
    if (flags().search && searchClose && !searchClose.dataset.bound) {
      searchClose.dataset.bound = "1";
      searchClose.addEventListener("click", hide);
    }
    if (flags().connectors) {
      var connectorOpen = $("connectorOpen");
      if (connectorOpen) connectorOpen.hidden = false;
      if (connectorOpen && !connectorOpen.dataset.bound) {
        connectorOpen.dataset.bound = "1";
        connectorOpen.addEventListener("click", function () {
          post({ op: "connectors" }).then(function (data) {
            var list = $("connectorList");
            if (!list) return;
            list.replaceChildren();
            (data.connectors || []).forEach(function (row) {
              if (!row.ready) return;
              var item = document.createElement("li");
              var button = document.createElement("button");
              button.type = "button";
              button.textContent = "Connect " + row.name;
              button.addEventListener("click", function () {
                post({ op: "connector-start", provider: row.id }).then(function (started) {
                  if (started.url) window.location.href = started.url;
                });
              });
              item.appendChild(button);
              list.appendChild(item);
            });
            if (!list.children.length) {
              var empty = document.createElement("li");
              empty.textContent = "Connectors stay hidden until their client ids are set.";
              list.appendChild(empty);
            }
            show("connectorCard");
          });
        });
      }
      var connectorClose = $("connectorClose");
      if (connectorClose && !connectorClose.dataset.bound) {
        connectorClose.dataset.bound = "1";
        connectorClose.addEventListener("click", hide);
      }
    }
    if (flags().vault) {
      var vaultOpen = $("vaultOpen");
      if (vaultOpen) vaultOpen.hidden = false;
      function paintVault(items) {
        var list = $("vaultList");
        if (!list) return;
        list.replaceChildren();
        (items || []).forEach(function (item) {
          var row = document.createElement("li");
          row.textContent = item.label + " " + item.value + " ";
          var button = document.createElement("button");
          button.type = "button";
          button.textContent = "Reveal";
          button.addEventListener("click", function () {
            var phrase = window.prompt("Passphrase");
            if (!phrase) return;
            post({ op: "vault-reveal", item_id: item.id, passphrase: phrase }).then(function (data) {
              row.textContent = data.ok ? item.label + " " + data.value : (data.error || "Locked");
            });
          });
          row.appendChild(button);
          list.appendChild(row);
        });
      }
      if (vaultOpen && !vaultOpen.dataset.bound) {
        vaultOpen.dataset.bound = "1";
        vaultOpen.addEventListener("click", function () {
          post({ op: "vault-list" }).then(function (data) {
            if (!data.ok) return;
            paintVault(data.items || []);
            show("vaultCard");
          });
        });
      }
      var vaultForm = $("vaultForm");
      if (vaultForm && !vaultForm.dataset.bound) {
        vaultForm.dataset.bound = "1";
        vaultForm.addEventListener("submit", function (event) {
          event.preventDefault();
          post({
            op: "vault-put",
            label: $("vaultLabel").value,
            value: $("vaultValue").value,
            passphrase: $("vaultPass").value
          }).then(function () {
            post({ op: "vault-list" }).then(function (data) { if (data.ok) paintVault(data.items || []); });
          });
        });
      }
      var vaultClose = $("vaultClose");
      if (vaultClose && !vaultClose.dataset.bound) {
        vaultClose.dataset.bound = "1";
        vaultClose.addEventListener("click", hide);
      }
    }
    if (flags().oauth) {
      var oauthButtons = window.simkoOauth || {};
      var google = $("googleSignIn");
      var apple = $("appleSignIn");
      if (google) google.hidden = !oauthButtons.google;
      if (apple) apple.hidden = !oauthButtons.apple;
      if ((oauthButtons.google || oauthButtons.apple) && $("accountSignIn") && !$("accountSignIn").dataset.oauth) {
        $("accountSignIn").dataset.oauth = "1";
        $("accountSignIn").addEventListener("click", function () {
          setTimeout(function () { show("oauthCard"); }, 0);
        });
      }
      function begin(provider) {
        fetch("/api/platform", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ op: "oauth-start", provider: provider })
        }).then(function (res) { return res.json(); }).then(function (data) {
          if (data.url) window.location.href = data.url;
        });
      }
      if (google && !google.dataset.bound) {
        google.dataset.bound = "1";
        google.addEventListener("click", function () { begin("google"); });
      }
      if (apple && !apple.dataset.bound) {
        apple.dataset.bound = "1";
        apple.addEventListener("click", function () { begin("apple"); });
      }
      var oauthClose = $("oauthClose");
      if (oauthClose && !oauthClose.dataset.bound) {
        oauthClose.dataset.bound = "1";
        oauthClose.addEventListener("click", hide);
      }
    }
    if (flags().shares) {
      var shareOpen = $("shareOpen");
      if (shareOpen) shareOpen.hidden = false;
      var shareToken = "";
      if (shareOpen && !shareOpen.dataset.bound) {
        shareOpen.dataset.bound = "1";
        shareOpen.addEventListener("click", function () { show("shareCard"); });
      }
      var shareCreate = $("shareCreate");
      if (shareCreate && !shareCreate.dataset.bound) {
        shareCreate.dataset.bound = "1";
        shareCreate.addEventListener("click", function () {
          post({ op: "share-lifebook" }).then(function (data) {
            if (!data.ok) return;
            shareToken = data.share.token;
            $("shareUrl").textContent = data.share.url;
            $("shareRevoke").hidden = false;
          });
        });
      }
      var shareRevoke = $("shareRevoke");
      if (shareRevoke && !shareRevoke.dataset.bound) {
        shareRevoke.dataset.bound = "1";
        shareRevoke.addEventListener("click", function () {
          post({ op: "revoke-share", share_token: shareToken }).then(function (data) {
            if (!data.ok) return;
            $("shareUrl").textContent = "That link is revoked.";
            shareRevoke.hidden = true;
          });
        });
      }
      var shareClose = $("shareClose");
      if (shareClose && !shareClose.dataset.bound) {
        shareClose.dataset.bound = "1";
        shareClose.addEventListener("click", hide);
      }
    }
    if (flags().images) {
      var imageOpen = $("imageOpen");
      if (imageOpen) imageOpen.hidden = false;
      function paintImages(rows) {
        var grid = $("imageGrid");
        if (!grid) return;
        grid.replaceChildren();
        (rows || []).forEach(function (row) {
          var img = document.createElement("img");
          img.src = row.url;
          img.alt = row.prompt;
          grid.appendChild(img);
        });
      }
      if (imageOpen && !imageOpen.dataset.bound) {
        imageOpen.dataset.bound = "1";
        imageOpen.addEventListener("click", function () {
          post({ op: "images" }).then(function (data) {
            if (!data.ok) return;
            paintImages(data.images || []);
            show("imageCard");
          });
        });
      }
      var imageForm = $("imageForm");
      if (imageForm && !imageForm.dataset.bound) {
        imageForm.dataset.bound = "1";
        imageForm.addEventListener("submit", function (event) {
          event.preventDefault();
          post({ op: "imagine", prompt: $("imagePrompt").value }).then(function (data) {
            if (!data.ok) return;
            paintImages(data.images || []);
          });
        });
      }
      var imageClose = $("imageClose");
      if (imageClose && !imageClose.dataset.bound) {
        imageClose.dataset.bound = "1";
        imageClose.addEventListener("click", hide);
      }
    }
    if (flags().routines) {
      var routineOpen = $("routineOpen");
      if (routineOpen) routineOpen.hidden = false;
      function paintRoutines(data) {
        var list = $("routineList");
        if (!list) return;
        list.replaceChildren();
        (data.deliveries || []).forEach(function (row) {
          var item = document.createElement("li");
          item.textContent = row.body;
          list.appendChild(item);
        });
        (data.routines || []).forEach(function (row) {
          var item = document.createElement("li");
          item.textContent = row.label + " at " + String(row.hour).padStart(2, "0") + ":" + String(row.minute).padStart(2, "0");
          list.appendChild(item);
        });
      }
      if (routineOpen && !routineOpen.dataset.bound) {
        routineOpen.dataset.bound = "1";
        routineOpen.addEventListener("click", function () {
          post({ op: "routines" }).then(function (data) {
            if (!data.ok) return;
            paintRoutines(data);
            show("routineCard");
          });
        });
      }
      var routineForm = $("routineForm");
      if (routineForm && !routineForm.dataset.bound) {
        routineForm.dataset.bound = "1";
        routineForm.addEventListener("submit", function (event) {
          event.preventDefault();
          post({
            op: "save-routine",
            kind: $("routineKind").value,
            hour: Number($("routineHour").value),
            minute: Number($("routineMinute").value)
          }).then(function () {
            post({ op: "routines" }).then(function (data) { if (data.ok) paintRoutines(data); });
          });
        });
      }
      var routineClose = $("routineClose");
      if (routineClose && !routineClose.dataset.bound) {
        routineClose.dataset.bound = "1";
        routineClose.addEventListener("click", hide);
      }
    }
    if (flags().memory) {
      var memoryOpen = $("memoryOpen");
      if (memoryOpen) memoryOpen.hidden = false;
      function paintMemories(rows) {
        var list = $("memoryList");
        if (!list) return;
        list.replaceChildren();
        (rows || []).forEach(function (row) {
          var item = document.createElement("li");
          item.textContent = row.fact + " ";
          var button = document.createElement("button");
          button.type = "button";
          button.textContent = "Delete";
          button.addEventListener("click", function () {
            post({ op: "forget", memory_id: row.id }).then(function (data) {
              if (data.ok) paintMemories(data.memories || []);
            });
          });
          item.appendChild(button);
          list.appendChild(item);
        });
        if (!(rows || []).length) {
          var empty = document.createElement("li");
          empty.textContent = "No memories yet.";
          list.appendChild(empty);
        }
      }
      if (memoryOpen && !memoryOpen.dataset.bound) {
        memoryOpen.dataset.bound = "1";
        memoryOpen.addEventListener("click", function () {
          post({ op: "memories" }).then(function (data) {
            if (!data.ok) return;
            paintMemories(data.memories || []);
            show("memoryCard");
          });
        });
      }
      var memoryClose = $("memoryClose");
      if (memoryClose && !memoryClose.dataset.bound) {
        memoryClose.dataset.bound = "1";
        memoryClose.addEventListener("click", hide);
      }
    }
    if (flags().approvals) {
      var yes = $("approvalYes");
      var no = $("approvalNo");
      var close = $("approvalClose");
      if (close && !close.dataset.bound) {
        close.dataset.bound = "1";
        close.addEventListener("click", hide);
      }
      function decide(decision) {
        if (!pendingApproval) return;
        var current = pendingApproval;
        post({ op: "decide", approval_id: current.approval.id, decision: decision }).then(function (data) {
          paintAudit((data && data.audit) || []);
          if (decision === "approve" && data.ok && current.retry) current.retry(current.approval.id);
          if (decision === "decline") hide();
        });
      }
      if (yes && !yes.dataset.bound) {
        yes.dataset.bound = "1";
        yes.addEventListener("click", function () { decide("approve"); });
      }
      if (no && !no.dataset.bound) {
        no.dataset.bound = "1";
        no.addEventListener("click", function () { decide("decline"); });
      }
    }
    if (!flags().paywall) return;
    var usage = $("usageOpen");
    if (usage) usage.hidden = false;
    if (usage && !usage.dataset.bound) {
      usage.dataset.bound = "1";
      usage.addEventListener("click", function () {
        post({ op: "usage" }).then(function (data) {
          if (!data.ok) return;
          paintUsage(data);
          show("usagePage");
        });
      });
    }
    [["paywallClose", hide], ["usageClose", hide]].forEach(function (pair) {
      var button = $(pair[0]);
      if (button && !button.dataset.bound) {
        button.dataset.bound = "1";
        button.addEventListener("click", pair[1]);
      }
    });
    var buy = $("paywallBuy");
    if (buy && !buy.dataset.bound) {
      buy.dataset.bound = "1";
      buy.addEventListener("click", function () {
        var note = $("paywallNote");
        post({ op: "checkout" }).then(function (data) {
          if (data.url) {
            if (note) note.textContent = "Checkout is ready. Opening Square does not charge you until you pay there.";
            window.location.href = data.url;
            return;
          }
          if (note) note.textContent = data.error || "Square is not connected yet. Nothing was charged.";
        });
      });
    }
    var trial = $("paywallTrial");
    if (trial && !trial.dataset.bound) {
      trial.dataset.bound = "1";
      trial.addEventListener("click", function () {
        post({ op: "start-trial" }).then(function (data) {
          var note = $("paywallNote");
          if (!data.ok) {
            if (note) note.textContent = data.error || "The trial could not start.";
            return;
          }
          if (note) note.textContent = "Free trial started. Nothing was charged.";
        });
      });
    }
    var box = $("everyday");
    if (box && !box.dataset.paywallBound) {
      box.dataset.paywallBound = "1";
      box.addEventListener("focus", function () {
        if (!signedIn()) {
          box.blur();
          var sign = $("accountSignIn");
          if (sign) sign.click();
        }
      });
    }
    var go = $("go");
    if (go && !go.dataset.paywallBound) {
      go.dataset.paywallBound = "1";
      go.addEventListener("click", function (event) {
        if (signedIn()) return;
        event.preventDefault();
        event.stopPropagation();
        var sign = $("accountSignIn");
        if (sign) sign.click();
      }, true);
    }
  }
  window.simcoPlatform = { boot: boot, showPaywall: showPaywall, showApproval: showApproval, showSources: showSources };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
