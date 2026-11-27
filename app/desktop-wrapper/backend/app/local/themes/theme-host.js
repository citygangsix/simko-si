/* Loads manifest themes, paints the picker, and pauses motion. */
(function () {
  var DEFAULT_ID = "reef-live";
  var STORAGE_KEY = "simcoTheme";
  var catalog = [];
  var ready = Promise.resolve();
  var scriptLoading = "";

  var motion = {
    idle: false,
    battery: false,
    idleMs: 20000,
    hiddenOverride: null,
    _timer: 0,
    refresh: function () {
      var reduced = false;
      try {
        reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      } catch (err) {
        reduced = false;
      }
      var hidden = this.hiddenOverride === null ? document.hidden : !!this.hiddenOverride;
      var plain = document.documentElement.getAttribute("data-theme") === "plain";
      var off = !!(this.idle || hidden || reduced || this.battery || plain);
      document.documentElement.dataset.motion = off ? "off" : "on";
      document.documentElement.classList.toggle("simco-turtle-paused", hidden);
      document.documentElement.classList.toggle("simco-turtle-idle", !!this.idle);
    },
    bump: function () {
      this.idle = false;
      window.clearTimeout(this._timer);
      var self = this;
      this.refresh();
      this._timer = window.setTimeout(function () {
        self.idle = true;
        self.refresh();
      }, this.idleMs);
    }
  };

  function byId(id) {
    for (var i = 0; i < catalog.length; i += 1) {
      if (catalog[i].id === id) return catalog[i];
    }
    return null;
  }

  function currentId() {
    return document.documentElement.getAttribute("data-theme") || DEFAULT_ID;
  }

  function readSaved() {
    try {
      return localStorage.getItem(STORAGE_KEY) || "";
    } catch (err) {
      return "";
    }
  }

  function writeSaved(id) {
    try {
      localStorage.setItem(STORAGE_KEY, id);
    } catch (err) {}
  }

  function stylesheet() {
    var link = document.getElementById("themeStylesheet");
    if (!link) {
      link = document.createElement("link");
      link.id = "themeStylesheet";
      link.rel = "stylesheet";
      document.head.appendChild(link);
    }
    return link;
  }

  function mountScript(theme) {
    if (window.simcoThemeLayer && window.simcoThemeLayer.unmount) window.simcoThemeLayer.unmount();
    var previous = document.getElementById("themeScript");
    if (previous) previous.remove();
    var stage = document.getElementById("themeStage");
    if (stage) stage.remove();
    window.simcoThemeLayer = null;
    if (!theme.script || !theme.animation) return;
    scriptLoading = theme.id;
    var script = document.createElement("script");
    script.id = "themeScript";
    script.src = "/themes/" + theme.id + "/" + theme.script;
    script.onload = function () {
      if (scriptLoading !== theme.id) return;
      if (document.documentElement.getAttribute("data-theme") !== theme.id) return;
      if (window.simcoThemeLayer && window.simcoThemeLayer.mount) window.simcoThemeLayer.mount();
    };
    document.body.appendChild(script);
  }

  function paintPicker() {
    var list = document.getElementById("themeList");
    if (!list) return;
    var selected = currentId();
    list.replaceChildren();
    catalog.forEach(function (theme) {
      var button = document.createElement("button");
      button.type = "button";
      button.dataset.themeId = theme.id;
      button.setAttribute("aria-pressed", theme.id === selected ? "true" : "false");
      var swatch = document.createElement("span");
      swatch.className = "themeSwatch";
      swatch.style.background = theme.preview || "#ccc";
      button.appendChild(swatch);
      button.appendChild(document.createTextNode(theme.name || theme.id));
      if (theme.disabled) {
        button.disabled = true;
        button.setAttribute("aria-disabled", "true");
        button.title = theme.note || "Not available";
      } else {
        button.addEventListener("click", function () {
          apply(theme.id);
        });
      }
      list.appendChild(button);
    });
  }

  function apply(id, opts) {
    opts = opts || {};
    var theme = byId(id) || byId(DEFAULT_ID) || catalog[0];
    if (theme && theme.disabled) theme = byId(DEFAULT_ID) || catalog[0];
    if (!theme) {
      document.documentElement.setAttribute("data-theme", id || DEFAULT_ID);
      return id || DEFAULT_ID;
    }
    document.documentElement.setAttribute("data-theme", theme.id);
    stylesheet().href = "/themes/" + theme.id + "/" + (theme.stylesheet || "theme.css");
    writeSaved(theme.id);
    mountScript(theme);
    paintPicker();
    motion.refresh();
    if (!opts.skipRemote && window.simcoUserToken) pushRemote(theme.id);
    return theme.id;
  }

  function pushRemote(id) {
    var token = window.simcoUserToken;
    if (!token) return;
    fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "set", token: token, theme: id })
    }).catch(function () {});
  }

  function syncFromServer() {
    var token = window.simcoUserToken;
    if (!token) return Promise.resolve();
    return ready.then(function () {
      return fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ op: "get", token: token })
      }).then(function (response) { return response.json(); }).then(function (data) {
        if (!data || !data.ok) return;
        if (data.theme) apply(data.theme, { skipRemote: true });
        else pushRemote(currentId());
      }).catch(function () {});
    });
  }

  function bindMotion() {
    document.addEventListener("visibilitychange", function () {
      motion.hiddenOverride = null;
      motion.refresh();
    });
    ["pointermove", "keydown", "touchstart"].forEach(function (name) {
      window.addEventListener(name, function () { motion.bump(); }, { passive: true });
    });
    if (navigator.getBattery) {
      navigator.getBattery().then(function (battery) {
        function readBattery() {
          motion.battery = battery.level < 0.2 && !battery.charging;
          motion.refresh();
        }
        readBattery();
        battery.addEventListener("levelchange", readBattery);
        battery.addEventListener("chargingchange", readBattery);
      }).catch(function () {});
    }
    motion.bump();
  }

  function start() {
    bindMotion();
    ready = fetch("/themes/manifest.json")
      .then(function (response) { return response.json(); })
      .then(function (doc) {
        catalog = (doc && doc.themes) || [];
        DEFAULT_ID = (doc && doc.default) || DEFAULT_ID;
        var saved = readSaved();
        var initial = byId(saved) && !byId(saved).disabled ? saved : (document.documentElement.getAttribute("data-theme") || DEFAULT_ID);
        if (byId(initial) && byId(initial).disabled) initial = DEFAULT_ID;
        if (!byId(initial)) initial = DEFAULT_ID;
        apply(initial, { skipRemote: true });
      })
      .catch(function () {
        paintPicker();
      });
  }

  window.simcoMotion = motion;
  window.simcoThemes = {
    apply: apply,
    syncFromServer: syncFromServer,
    current: currentId
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
