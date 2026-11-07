import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const SITE = "http://127.0.0.1:8741";
const MOCK = "http://127.0.0.1:8742";

function writeConfig() {
  writeFileSync("/workspace/simkosi-private/config.php", `<?php
declare(strict_types=1);
return [
    'xai_api_key' => 'xai-local-mock',
    'xai_base_url' => '${MOCK}/v1',
    'model' => 'grok-4.7',
    'stt_model' => 'grok-voice-transcribe-2.0',
    'timeout_seconds' => 20,
    'max_input_chars' => 8000,
    'system_prompt' => 'You are Simko SI. Reply in everyday English.',
    'mail_mode' => 'dev',
    'extra_origins' => [],
    'installers' => [],
    'supabase' => [
        'enabled' => false,
        'project_ref' => 'wxvjajecvklfjxppawdx',
        'url' => '',
        'service_key' => '',
    ],
];
`);
}

function start(args) {
  const child = spawn("php", args, { cwd: "/workspace", stdio: ["ignore", "pipe", "pipe"] });
  child.stderr.on("data", (buf) => {
    const line = String(buf);
    if (!/Development Server|Accepted|Closing/.test(line)) process.stderr.write(line);
  });
  return child;
}

async function waitFor(url) {
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch (error) {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("not up " + url);
}

async function post(path, body) {
  const response = await fetch(SITE + path, {
    method: "POST",
    headers: { Origin: SITE, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}

function watch(page, problems) {
  page.on("pageerror", (error) => problems.push("pageerror " + error.message));
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (/favicon|net::ERR|Failed to load resource/i.test(text)) return;
    problems.push("console " + text);
  });
  page.on("response", (response) => {
    if (response.status() < 400) return;
    problems.push(response.status() + " " + response.url());
  });
}

async function openTools(page) {
  if (await page.locator("#drawer").isVisible()) return;
  if (!(await page.locator("#toolsToggle").isVisible())) {
    await page.evaluate(() => document.body.classList.remove("thread-open"));
  }
  await page.click("#toolsToggle");
  await page.locator("#drawer").waitFor({ state: "visible" });
}

async function ensureThread(page) {
  if (await page.locator("#everyday").isVisible()) return;
  await page.locator("#sessionList button").first().click();
  await page.locator("#everyday").waitFor({ state: "visible" });
}

async function closeTools(page) {
  await page.evaluate(() => {
    const drawer = document.getElementById("drawer");
    if (drawer) drawer.hidden = true;
    const toggle = document.getElementById("toolsToggle");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
  });
}

async function closeModal(page) {
  if (await page.locator("#authModal").isVisible()) await page.click("#authModalClose");
  await page.locator("#authModal").waitFor({ state: "hidden" });
}

async function visibleBox(page, selector) {
  const box = await page.locator(selector).boundingBox();
  if (!box || box.width < 8 || box.height < 8) throw new Error(selector + " is not visible");
  return box;
}

async function sessionCase(browser) {
  const email = `kept-${Date.now()}@simkosi.test`;
  const signed = await post("/api/auth", { op: "signup", email, password: "reef-turtle-8" });
  if (!signed.ok || !signed.token) throw new Error("session fixture signup failed");
  const token = signed.token;

  async function openWith(storageToken, cookieToken) {
    const context = await browser.newContext();
    if (cookieToken) {
      await context.addCookies([{
        name: "simko",
        value: cookieToken,
        url: SITE,
        httpOnly: true,
        sameSite: "Lax",
      }]);
    }
    await context.addInitScript((value) => {
      sessionStorage.setItem("podcoderToken", value);
    }, storageToken);
    const page = await context.newPage({ viewport: { width: 1280, height: 800 } });
    const problems = [];
    watch(page, problems);
    await page.goto(SITE + "/?v=buttons", { waitUntil: "domcontentloaded" });
    return { context, page, problems };
  }

  const valid = await openWith(token, token);
  await valid.page.waitForFunction((address) => (document.getElementById("accountEmail").title || "") === address, email);
  if (await valid.page.locator("#accountSignIn").isVisible()) throw new Error("valid session still shows Sign in");
  await valid.page.reload({ waitUntil: "domcontentloaded" });
  await valid.page.waitForFunction((address) => (document.getElementById("accountEmail").title || "") === address, email);
  await valid.page.screenshot({ path: "/opt/cursor/artifacts/simko-session-header-1280x800.png" });
  if (valid.problems.length) throw new Error("valid session errors " + valid.problems.join(" | "));
  await valid.context.close();

  const mixed = await openWith("stale-not-a-session", token);
  await mixed.page.waitForFunction((address) => (document.getElementById("accountEmail").title || "") === address, email, { timeout: 8000 });
  if (await mixed.page.locator("#accountSignIn").isVisible()) throw new Error("cookie session still shows a dead Sign in");
  if (mixed.problems.length) throw new Error("cookie session errors " + mixed.problems.join(" | "));
  await mixed.context.close();

  const stale = await openWith("stale-not-a-session", "also-stale");
  await stale.page.locator("#accountSignIn").waitFor({ state: "visible" });
  await stale.page.click("#accountSignIn");
  await stale.page.locator("#authModal").waitFor({ state: "visible" });
  await stale.page.click("#authModalClose");
  if (stale.problems.length) throw new Error("stale session errors " + stale.problems.join(" | "));
  await stale.context.close();
  console.log("session header cases passed");
}

async function auditSignedOut(page) {
  await visibleBox(page, "#accountSignIn");
  await page.click("#accountSignIn");
  await page.locator("#authModal").waitFor({ state: "visible" });
  await page.click("#authTabUp");
  if ((await page.locator("#authModalTitle").innerText()) !== "Create account") throw new Error("create account tab");
  await page.click("#authTabIn");
  if ((await page.locator("#authModalTitle").innerText()) !== "Sign in") throw new Error("sign in tab");
  await page.click("#authForgot");
  await page.locator("#authResetForm").waitFor({ state: "visible" });
  await page.click("#authResetBack");
  await page.locator("#authModalForm").waitFor({ state: "visible" });
  await closeModal(page);

  await openTools(page);
  await page.click("#signUp");
  await page.locator("#authModalTitle").waitFor();
  if ((await page.locator("#authModalTitle").innerText()) !== "Create account") throw new Error("drawer sign up");
  await closeModal(page);
  await openTools(page);
  await page.click("#signIn");
  if ((await page.locator("#authModalTitle").innerText()) !== "Sign in") throw new Error("drawer sign in");
  await closeModal(page);
  await openTools(page);
  if (await page.locator("#resetPassword").isVisible()) {
    await page.click("#resetPassword");
    await page.locator("#authResetForm").waitFor({ state: "visible" });
    await closeModal(page);
  }

  await closeTools(page);
  await page.click("#searchChats");
  await page.locator("#chatSearch").waitFor({ state: "visible" });
  await page.fill("#chatSearch", "career");
  await page.waitForFunction(() => (document.getElementById("sessionList").innerText || "").includes("Career"));
  await page.fill("#chatSearch", "");
  await page.locator("#sessionList button", { hasText: "Health check" }).click();
  await page.waitForFunction(() => document.getElementById("threadTitle").textContent === "Health check");
  if (await page.locator("#backToList").isVisible()) {
    await page.click("#backToList");
    await page.locator("#newChat").waitFor({ state: "visible" });
  }

  await page.click("#newChat");
  await page.locator("#authModal").waitFor({ state: "visible" });
  await closeModal(page);
  await ensureThread(page);
  await page.locator("#everyday").fill("hello from the button audit");
  await page.click("#go");
  await page.locator("#authModal").waitFor({ state: "visible" });
  await closeModal(page);
  await page.locator("#everyday").fill("");
  if (!(await page.locator("#sendToChat").isVisible()) && await page.locator("#backToList").isVisible()) {
    await page.click("#backToList");
  }
  await page.click("#sendToChat");
  await page.locator("#authModal").waitFor({ state: "visible" });
  await closeModal(page);

  await openTools(page);
  await page.locator("#lifebook > summary").click();
  await page.locator("#lifeTags button").first().click();
  await page.waitForFunction(() => (document.getElementById("lifeLast").textContent || "").includes("Sign in") || !document.getElementById("authModal").hidden);
  await closeModal(page);
  await openTools(page);
  await page.locator("#lifeCounts summary").click();
  if (!(await page.locator("#lifeCountBody").isVisible())) throw new Error("counts");
  await page.locator("#themeList button", { hasText: "Plain" }).click();
  await page.waitForFunction(() => document.documentElement.getAttribute("data-theme") === "plain");
  await page.locator("#themeList button", { hasText: "Reef" }).click();
  await page.locator("#voiceList button.voicePick").nth(1).click();
  await page.waitForFunction(() => document.getElementById("voiceNow").textContent !== "Coral");
  const voiceBefore = await page.locator("#voiceNow").innerText();
  await page.locator("#voiceList button.voicePlay").first().click();
  await page.waitForFunction((name) => document.getElementById("voiceNow").textContent === name, voiceBefore);
  await page.locator("#voiceSpeed").fill("1.3");
  await page.click("#voiceSpeedReset");
  await page.waitForFunction(() => (document.getElementById("voiceSpeedOut").textContent || "").includes("1"));

  await page.click("#roleVideo");
  await closeTools(page);
  await ensureThread(page);
  await page.locator("#gallery").waitFor({ state: "visible" });
  await openTools(page);
  await page.click("#roleImage");
  await closeTools(page);
  await ensureThread(page);
  if (!(await page.locator("#gallery").isVisible())) throw new Error("image gallery");
  await openTools(page);
  await page.click("#roleCoding");
  await closeTools(page);
  await ensureThread(page);
  await page.locator("#gallery").waitFor({ state: "hidden" });
  await openTools(page);
  await page.click("#detectHardware");
  await page.waitForFunction(() => /browser|Recommended/i.test(document.getElementById("reply-bubble").textContent || ""));
  await page.click("#downloadNow");
  await page.waitForFunction(() => (document.getElementById("reply-bubble").textContent || "").includes("coming soon"));
  await page.click("#advancedLink");
  await page.locator("#advancedNote").waitFor({ state: "visible" });
  await page.click("#whatRent");
  await page.waitForFunction(() => /GPU|desktop app/i.test(document.getElementById("autoOffer").textContent || ""));
  await page.click("#confirmRentGo");
  await page.waitForFunction(() => /turned off/i.test(document.getElementById("reply-bubble").textContent || ""));
  await page.click("#openHost");
  await page.locator("#hostRow").waitFor({ state: "visible" });
  await page.click("#hostSave");
  await page.waitForFunction(() => /website|Grok/i.test(document.getElementById("hostHint").textContent || ""));
  await page.click("#turtlePeek");
  await page.locator("#turtleScreen").waitFor({ state: "hidden" });
  await openTools(page);
  await page.click("#openTurtle");
  await page.locator("#turtleScreen").waitFor({ state: "visible" });
  await page.click("#turtleRedetect");
  await page.waitForFunction(() => (document.getElementById("turtleLog").textContent || "").length > 10);
  await page.click("#turtleCheck");
  await page.waitForFunction(() => /desktop|coming soon/i.test(document.getElementById("turtleError").textContent || document.getElementById("turtleLead").textContent || ""));
  await page.locator("#turtleQuestion").fill("");
  await page.click("#turtleAskSend");
  await page.waitForFunction(() => (document.getElementById("turtleError").textContent || "").includes("Type"));
  await page.click("#turtlePeek");
  await page.locator("#turtleScreen").waitFor({ state: "hidden" });

  await ensureThread(page);
  await page.click("#micButton");
  await page.waitForFunction(() => {
    const mic = document.getElementById("micButton");
    const hint = document.getElementById("micHint");
    return mic.dataset.state === "listening" || (hint && !hint.hidden && hint.textContent);
  });
  if ((await page.locator("#micButton").getAttribute("data-state")) === "listening") await page.click("#micButton");

  await page.locator("#raw summary").click();
  await page.waitForFunction(() => document.getElementById("raw").open);
  for (const id of ["#computeCloud", "#computeLocal", "#rentComputer", "#confirmEmail", "#setPassword", "#turtleEnter"]) {
    if (await page.locator(id).isVisible()) throw new Error(id + " should stay hidden");
  }
  await closeTools(page);
}

async function auditSignedIn(page, width) {
  await ensureThread(page);
  await page.locator("#everyday").click();
  await page.locator("#everyday").pressSequentially("Button audit hello", { delay: 8 });
  await page.click("#go");
  await page.waitForFunction(() => (document.getElementById("reply-bubble").textContent || "").includes("The reef heard you"));
  await visibleBox(page, "#replySpeak.is-shown");
  if (width === 1280) await page.screenshot({ path: "/opt/cursor/artifacts/simko-speaker-1280x800.png" });
  if (width === 390) await page.screenshot({ path: "/opt/cursor/artifacts/simko-speaker-390x844.png" });
  await page.click("#replySpeak");
  const before = await page.locator("#threadTitle").innerText();
  if (!(await page.locator("#newChat").isVisible()) && await page.locator("#backToList").isVisible()) {
    await page.click("#backToList");
  }
  await page.click("#newChat");
  await page.waitForFunction((prev) => document.getElementById("threadTitle").textContent !== prev, before);
  await ensureThread(page);
  await page.locator("#everyday").fill("A note for relay");
  if (!(await page.locator("#sendToChat").isVisible()) && await page.locator("#backToList").isVisible()) {
    await page.click("#backToList");
  }
  await page.click("#sendToChat");
  await page.locator("#relayTarget").waitFor({ state: "visible" });
  await page.click("#relayGo");
  await page.waitForFunction(() => (document.getElementById("historyBubbles").innerText || "").includes("Sent to"));
  await openTools(page);
  await page.locator("#lifeTags button").first().click();
  await page.waitForFunction(() => (document.getElementById("lifeLast").textContent || "").length > 0);
  await closeTools(page);
}

writeConfig();
const mock = start(["-S", "127.0.0.1:8742", "-t", "tests", "tests/mock-xai.php"]);
const site = start(["-S", "127.0.0.1:8741", "-t", "public_html", "public_html/router.php"]);
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--mute-audio"] });

try {
  await waitFor(SITE + "/api/health");
  mkdirSync("/opt/cursor/artifacts", { recursive: true });
  await sessionCase(browser);

  for (const [width, height] of [[1280, 800], [390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height } });
    const problems = [];
    watch(page, problems);
    await page.goto(SITE + "/", { waitUntil: "domcontentloaded" });
    await page.locator("#accountSignIn").waitFor({ state: "visible" });
    await auditSignedOut(page);
    const email = `audit-${width}-${Date.now()}@simkosi.test`;
    await page.click("#accountSignIn");
    await page.click("#authTabUp");
    await page.locator("#modalEmail").fill(email);
    await page.locator("#modalPassword").fill("reef-turtle-8");
    await page.click("#authModalSubmit");
    await page.waitForFunction((address) => (document.getElementById("accountEmail").title || "") === address, email);
    await auditSignedIn(page, width);
    await page.click("#accountSignOut");
    await page.locator("#accountSignIn").waitFor({ state: "visible" });
    if (problems.length) throw new Error(width + " problems " + problems.join(" | "));
    await page.close();
    console.log("button audit passed", width + "x" + height);
  }
  console.log("buttons ok");
} finally {
  await browser.close();
  site.kill("SIGTERM");
  mock.kill("SIGTERM");
}
