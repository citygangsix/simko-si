import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const SITE = "http://127.0.0.1:8775";
const privateDir = "/tmp/simko-family-mock";
mkdirSync(privateDir + "/data", { recursive: true });
mkdirSync("/opt/cursor/artifacts/simkosi-family", { recursive: true });
writeFileSync(privateDir + "/config.php", `<?php
declare(strict_types=1);
return [
    'xai_api_key' => 'xai-local-mock',
    'xai_base_url' => 'http://127.0.0.1:9/v1',
    'model' => 'grok-4.7',
    'mail_mode' => 'dev',
    'site_url' => 'https://simkosi.com',
    'family_ui' => false,
    'max_input_chars' => 8000,
];
`);

const site = spawn("php", ["-S", "127.0.0.1:8775", "-t", "public_html", "public_html/router.php"], {
  cwd: "/workspace",
  env: { ...process.env, SIMKOSI_PRIVATE: privateDir },
  stdio: ["ignore", "pipe", "pipe"],
});
site.stderr.on("data", () => {});

async function waitHealth() {
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(SITE + "/api/health")).ok) return;
    } catch (error) {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("mock site not up");
}

async function shot(page, width, height, name) {
  await page.setViewportSize({ width, height });
  await page.screenshot({ path: "/opt/cursor/artifacts/simkosi-family/" + name });
}

const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--mute-audio"] });
try {
  await waitHealth();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await page.goto(SITE + "/?family=1", { waitUntil: "domcontentloaded" });
  await page.click("#accountSignIn");
  await page.click("#authTabUp");
  await page.locator("#parentConsentRow").waitFor({ state: "visible" });
  await page.locator("#modalEmail").fill("parent@simkosi.test");
  await page.locator("#modalPassword").fill("reef-turtle-8");
  await page.locator("#parentConsent").check();
  await shot(page, 1280, 800, "signup-1280.png");
  await shot(page, 390, 844, "signup-390.png");

  const responsePromise = page.waitForResponse((response) => response.url().includes("/api/auth") && response.request().method() === "POST");
  await page.click("#authModalSubmit");
  const signup = await (await responsePromise).json();
  if (!signup.ok || !signup.dev_token) throw new Error("dev signup did not return a confirm code");
  await page.waitForFunction(() => (document.getElementById("accountEmail").title || "") === "parent@simkosi.test");
  await page.evaluate(async ({ token, code }) => {
    await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "confirm-email", confirm_token: code, token }),
    });
    for (const child of [
      { display_name: "Lumen", avatar: "turtle", age_band: "Ages 7 to 9" },
      { display_name: "Nix", avatar: "dolphin", age_band: "Ages 10 to 12" },
    ]) {
      const created = await fetch("/api/family", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ op: "create-child", token, ...child }),
      }).then((res) => res.json());
      const title = child.display_name === "Lumen" ? "Bedtime story" : "Homework help";
      await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ op: "create", token, title, child_id: created.child.id }),
      });
    }
  }, { token: signup.token, code: signup.dev_token });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.locator("#familyOpen").waitFor({ state: "visible" });
  await page.locator("#familyOpen").click();
  await page.locator("#familyKids").waitFor({ state: "visible" });
  await page.waitForFunction(() => (document.getElementById("familyKids").innerText || "").includes("Lumen") && (document.getElementById("familyKids").innerText || "").includes("Bedtime story"));
  await shot(page, 1280, 800, "dashboard-1280.png");
  await shot(page, 390, 844, "dashboard-390.png");
  await page.click("#familyAddOpen");
  await page.locator("#familyAddTitle").waitFor({ state: "visible" });
  await page.locator("#childName").fill("Pebble");
  await shot(page, 1280, 800, "add-child-1280.png");
  await shot(page, 390, 844, "add-child-390.png");
  await page.click("#familyAddClose");
  await page.click("#familyPickOpen");
  await page.locator("#familyPickTitle").waitFor({ state: "visible" });
  await page.waitForFunction(() => (document.getElementById("familyPickList").innerText || "").includes("Nix"));
  await shot(page, 1280, 800, "picker-1280.png");
  await shot(page, 390, 844, "picker-390.png");

  const plain = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await plain.goto(SITE + "/", { waitUntil: "domcontentloaded" });
  await plain.click("#accountSignIn");
  await plain.click("#authTabUp");
  if (await plain.locator("#parentConsentRow").isVisible()) throw new Error("consent checkbox is visible while the family flag is off");
  if (await plain.locator("#familyOpen").isVisible()) throw new Error("family button is visible while the family flag is off");
  if (await plain.locator("#familyStage").isVisible()) throw new Error("family stage is visible while the family flag is off");
  console.log("family mockups saved and the flag stays off");
} finally {
  await browser.close();
  site.kill("SIGTERM");
}
