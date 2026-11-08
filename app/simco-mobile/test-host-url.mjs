import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../podcoder-translator-renter/local/simco-client.js", import.meta.url), "utf8");
const store = new Map();
const sandbox = {
  URL,
  fetch() { return Promise.resolve({ ok: true }); },
  localStorage: {
    getItem(key) { return store.has(key) ? store.get(key) : null; },
    setItem(key, value) { store.set(key, String(value)); },
    removeItem(key) { store.delete(key); },
  },
  location: { href: "https://localhost/index.html", origin: "https://localhost" },
  Capacitor: { isNativePlatform() { return true; } },
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(source, sandbox);

const host = sandbox.simcoHost;
assert.equal(host.appId, "com.simkosi.simcosi");
assert.equal(host.normalize("http://192.168.1.20:8788/"), "http://192.168.1.20:8788");
assert.equal(host.normalize("https://example.trycloudflare.com"), "");
assert.equal(host.normalize("javascript:alert(1)"), "");
assert.equal(host.normalize("http://user:secret@192.168.1.20"), "");
assert.equal(host.needsHost(), true);
const saved = host.save("http://192.168.1.20:8788");
assert.equal(saved.ok, true);
assert.equal(host.needsHost(), false);
assert.equal(host.rewrite("/api/setup"), "http://192.168.1.20:8788/api/setup");
assert.equal(host.rewrite("https://localhost/api/health"), "http://192.168.1.20:8788/api/health");
assert.equal(host.rewrite("/coral-reef-bg.jpg"), "/coral-reef-bg.jpg");
const refused = host.save("https://demo.trycloudflare.com");
assert.equal(refused.ok, false);
console.log("host url ok");
