import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";

const feature = process.argv[2] || "paywall";
const port = Number(process.argv[3] || 8801);
const mockPort = port + 1;
const root = "/workspace";
const privateDir = `/tmp/simko-mock-${feature}-${process.pid}`;
mkdirSync(`${privateDir}/data`, { recursive: true });
mkdirSync("/opt/cursor/artifacts/simkosi-platform", { recursive: true });

const flags = {
  paywall: false, approvals: false, search: false, memory: false, routines: false,
  images: false, shares: false, oauth: false, vault: false, connectors: false,
  agents: false, team: false, calls: false, browse: false, store: false,
};
flags[feature] = true;
const config = {
  xai_api_key: "xai-local-mock",
  xai_base_url: `http://127.0.0.1:${mockPort}/v1`,
  model: "grok-4.7",
  mail_mode: "dev",
  site_url: "https://simkosi.com",
  family_ui: false,
  max_input_chars: 8000,
  platform: flags,
  square: { environment: "sandbox", application_id: "", location_id: "", access_token: "", api_base: "https://connect.squareupsandbox.com" },
  search_blocklist: ["casino", "porn"],
  browse_allow: ["example.com", "simkosi.com"],
};
writeFileSync(`${privateDir}/config.php`, `<?php\ndeclare(strict_types=1);\nreturn ${JSON.stringify(config).replace(/\u2028/g, "\\u2028")};\n`.replace(
  /^return /,
  "return "
));
// JSON is not valid PHP. Write var-like PHP instead.
writeFileSync(`${privateDir}/config.php`, `<?php
declare(strict_types=1);
return json_decode('${JSON.stringify(config).replace(/'/g, "\\'")}', true);
`);

function start(args, env = {}) {
  const child = spawn("php", args, { cwd: root, env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] });
  child.stderr.on("data", () => {});
  return child;
}

async function waitHealth(url) {
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    try { if ((await fetch(url)).ok) return; } catch (error) {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("not up " + url);
}

const mock = start(["-S", `127.0.0.1:${mockPort}`, "-t", "tests", "tests/mock-xai.php"]);
const site = start(["-S", `127.0.0.1:${port}`, "-t", "public_html", "public_html/router.php"], { SIMKOSI_PRIVATE: privateDir });

const { chromium } = await import("playwright");
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--mute-audio"] });
const shots = [];
async function shot(page, width, name) {
  await page.setViewportSize({ width, height: width < 500 ? 844 : 800 });
  const path = `/opt/cursor/artifacts/simkosi-platform/${feature}-${name}-${width}.png`;
  await page.screenshot({ path });
  shots.push(path);
}

try {
  await waitHealth(`http://127.0.0.1:${port}/api/health`);
  await fetch(`http://127.0.0.1:${mockPort}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ messages: [{ role: "user", content: "ping" }] }),
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const email = `${feature}-${Date.now()}@simkosi.test`;
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: "domcontentloaded" });
  await page.click("#accountSignIn");
  await page.click("#authTabUp");
  await page.locator("#modalEmail").fill(email);
  await page.locator("#modalPassword").fill("reef-turtle-8");
  const auth = page.waitForResponse((response) => response.url().includes("/api/auth") && response.request().method() === "POST");
  await page.click("#authModalSubmit");
  const signup = await (await auth).json();
  if (!signup.token) throw new Error("no token");
  await page.waitForFunction((address) => (document.getElementById("accountEmail").title || "") === address, email);
  globalThis.__page = page;
  globalThis.__token = signup.token;
  globalThis.__base = `http://127.0.0.1:${port}`;
  globalThis.__shot = shot;
  globalThis.__feature = feature;
  const mod = await import(`./platform-shot-${feature}.mjs`);
  await mod.default(page, shot, signup.token);
  console.log(shots.join("\n"));
} finally {
  await browser.close();
  site.kill("SIGTERM");
  mock.kill("SIGTERM");
}
