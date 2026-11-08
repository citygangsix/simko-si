/* Simco SI phone client.
   The app id lives in simco-mobile/app.config.json (com.simkosi.simcosi).
   This file only remembers the host computer and sends /api calls there.
   It never embeds a tunnel address. */
(function () {
  var KEY = "simcoBackendUrl";

  function normalize(value) {
    var text = String(value || "").trim();
    if (!text) return "";
    var parsed;
    try {
      parsed = new URL(text);
    } catch (err) {
      return "";
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    if (parsed.username || parsed.password) return "";
    if (!parsed.hostname) return "";
    if (parsed.hostname === "trycloudflare.com" || parsed.hostname.endsWith(".trycloudflare.com")) return "";
    var path = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/$/, "");
    return parsed.origin + path;
  }

  function current() {
    try {
      return normalize(localStorage.getItem(KEY) || "");
    } catch (err) {
      return "";
    }
  }

  function nativeApp() {
    try {
      return !!(window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform());
    } catch (err) {
      return false;
    }
  }

  function needsHost() {
    return nativeApp() && !current();
  }

  function save(value) {
    var clean = normalize(value);
    if (!clean) {
      return {
        ok: false,
        error: "Use the computer's own http or https address, such as http://192.168.1.20:8788."
      };
    }
    localStorage.setItem(KEY, clean);
    return { ok: true, url: clean };
  }

  function clear() {
    try {
      localStorage.removeItem(KEY);
    } catch (err) {}
  }

  function rewrite(url) {
    var base = current();
    if (!base || !url) return url;
    var parsed;
    try {
      parsed = new URL(url, location.href);
    } catch (err) {
      return url;
    }
    var path = parsed.pathname || "";
    if (!(path === "/api" || path.indexOf("/api/") === 0)) return url;
    var relative = url.charAt(0) === "/";
    var same = parsed.origin === location.origin;
    if (!relative && !same) return url;
    return base + path + (parsed.search || "");
  }

  var orig = window.fetch.bind(window);
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var next = rewrite(url);
    if (next === url) return orig(input, init);
    if (typeof input === "string") return orig(next, init);
    return orig(new Request(next, input), init);
  };

  window.simcoHost = {
    key: KEY,
    appId: "com.simkosi.simcosi",
    current: current,
    normalize: normalize,
    save: save,
    clear: clear,
    needsHost: needsHost,
    native: nativeApp,
    rewrite: rewrite
  };
})();
