import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const SITE = "http://127.0.0.1:8741";
const MOCK = "http://127.0.0.1:8742";
const ORIGIN = { Origin: SITE, "Content-Type": "application/json" };

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
  child.stdout.on("data", () => {});
  child.stderr.on("data", (buf) => {
    const line = String(buf);
    if (!/Development Server|Accepted|Closing/.test(line)) process.stderr.write(line);
  });
  return child;
}

async function waitFor(url) {
  const deadline = Date.now() + 8000;
  let last = "";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      last = String(response.status);
    } catch (error) {
      last = error.message;
    }
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("not up: " + url + " " + last);
}

async function post(path, body, origin = SITE) {
  const response = await fetch(SITE + path, {
    method: "POST",
    headers: { Origin: origin, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  return { status: response.status, data };
}

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

async function apiTests() {
  const health = await fetch(SITE + "/api/health");
  assert(health.ok, "health failed");

  const voices = await fetch(SITE + "/api/voice/voices");
  const voiceData = await voices.json();
  assert(voiceData.voices.length === 28, "expected 28 voices, got " + voiceData.voices.length);

  const getTurn = await fetch(SITE + "/api/simco/turn", { headers: { Origin: SITE } });
  const getBody = await getTurn.json();
  assert(getTurn.status === 405, "GET turn should be 405, got " + getTurn.status);
  assert(/posted/i.test(getBody.error || ""), "GET error should be friendly");

  const badOrigin = await post("/api/auth", { op: "me" }, "https://evil.example");
  assert(badOrigin.status === 403, "cross origin should be 403, got " + badOrigin.status);

  const email = `cap-${Date.now()}@simkosi.test`;
  const signed = await post("/api/auth", { op: "signup", email, password: "reef-turtle-8" });
  assert(signed.data.ok && signed.data.token, "signup failed " + JSON.stringify(signed.data));
  const token = signed.data.token;

  const created = await post("/api/sessions", { op: "create", token, title: "Cap" });
  assert(created.data.session && created.data.session.id, "create chat failed");
  const sessionId = created.data.session.id;

  const tooLong = await post("/api/simco/turn", { token, session_id: sessionId, text: "a".repeat(8001) });
  assert(tooLong.status === 413, "long message should be 413, got " + tooLong.status);
  assert(/8000/.test(tooLong.data.everyday || ""), "long message should explain the limit");

  let failures = 0;
  for (let i = 0; i < 40; i++) {
    const turn = await post("/api/simco/turn", { token, session_id: sessionId, text: "ping " + i });
    if (turn.status !== 200 || !String(turn.data.everyday || "").includes("ping " + i)) failures++;
  }
  assert(failures === 0, "uncapped turns failed: " + failures);

  const other = await post("/api/sessions", { op: "create", token, title: "Other" });
  const relay = await post("/api/sessions", {
    op: "relay",
    token,
    from_session_id: sessionId,
    to_session_id: other.data.session.id,
    text: "API note",
  });
  assert(relay.data.ok, "api relay failed " + JSON.stringify(relay.data));
  const fetched = await post("/api/sessions", { op: "get", token, session_id: other.data.session.id });
  const relayed = (fetched.data.session.messages || []).some((message) => message.role === "relay" && message.text === "API note");
  assert(relayed, "relay message missing on the other chat");
  console.log("api tests passed (40 uncapped turns, 8k guard, relay)");
}

async function shot(page, width, height, file, threadOpen) {
  await page.setViewportSize({ width, height });
  if (threadOpen !== undefined) {
    await page.evaluate((open) => document.body.classList.toggle("thread-open", open), threadOpen);
  }
  await page.evaluate(() => (document.fonts ? document.fonts.ready : Promise.resolve()));
  await page.screenshot({ path: file });
  console.log("saved", file);
}

async function browserTests() {
  mkdirSync("/opt/cursor/artifacts", { recursive: true });
  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: ["--autoplay-policy=no-user-gesture-required", "--mute-audio"],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.on("pageerror", (error) => console.log("PAGE", error.message));
  const email = `ui-${Date.now()}@simkosi.test`;
  await page.goto(SITE + "/", { waitUntil: "domcontentloaded" });
  for (const [width, height] of [[390, 844], [412, 848], [750, 832], [1280, 800]]) {
    await page.setViewportSize({ width, height });
    const box = await page.locator("#accountSignIn").boundingBox();
    const vp = page.viewportSize();
    if (!box || box.width < 8 || box.y < 0 || box.x < 0 || box.x + box.width > vp.width + 1 || box.y + box.height > vp.height + 1) {
      throw new Error("Sign in button is not on screen at " + width + "x" + height);
    }
  }
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.click("#accountSignIn");
  await page.locator("#authModal").waitFor({ state: "visible" });
  await page.click("#authTabUp");
  await page.locator("#authModalTitle").waitFor();
  await shot(page, 1280, 800, "/opt/cursor/artifacts/simko-signin-1280x800.png");
  await shot(page, 390, 844, "/opt/cursor/artifacts/simko-signin-390x844.png");
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.locator("#modalEmail").click();
  await page.locator("#modalEmail").pressSequentially(email, { delay: 12 });
  await page.locator("#modalPassword").click();
  await page.locator("#modalPassword").pressSequentially("reef-turtle-8", { delay: 12 });
  await page.click("#authModalSubmit");
  await page.waitForFunction((address) => (document.getElementById("accountEmail").textContent || "").length > 0 && (document.getElementById("accountEmail").title || "").includes(address), email);
  await page.locator("#authModal").waitFor({ state: "hidden" });
  await page.waitForFunction(() => {
    const button = document.querySelector("#sessionList button");
    return button && !String(button.dataset.id || "").startsWith("demo-");
  });

  const box = page.locator("#everyday");
  await box.click();
  await box.pressSequentially("Hello sea turtle", { delay: 30 });
  await page.click("#go");
  await page.waitForFunction(() => {
    const text = document.getElementById("reply-bubble").textContent || "";
    return text.includes("The reef heard you") && text.includes("Hello sea turtle");
  }, null, { timeout: 20000 });
  await page.locator("#replySpeak").waitFor({ state: "visible" });
  console.log("typed turn returned a reply with a speaker button");

  await shot(page, 1280, 800, "/opt/cursor/artifacts/simko-1280x800.png", false);
  await shot(page, 390, 844, "/opt/cursor/artifacts/simko-390x844.png", true);
  await shot(page, 412, 848, "/opt/cursor/artifacts/simko-folded-412x848.png", true);
  await shot(page, 750, 832, "/opt/cursor/artifacts/simko-unfolded-750x832.png", false);

  await page.setViewportSize({ width: 1280, height: 800 });
  const before = await page.locator("#threadTitle").innerText();
  await page.click("#newChat");
  await page.waitForFunction((prev) => (document.getElementById("threadTitle").textContent || "") !== prev, before);
  await page.locator("#everyday").click();
  await page.locator("#everyday").pressSequentially("Note for the other chat", { delay: 20 });
  await page.click("#sendToChat");
  await page.locator("#relayTarget option").first().waitFor({ state: "attached" });
  await page.click("#relayGo");
  await page.waitForFunction(() => (document.getElementById("historyBubbles").innerText || "").includes("Sent to"));
  await page.locator("#sessionList button", { hasText: "Hello sea turtle" }).click();
  await page.waitForFunction(() => (document.getElementById("reply-bubble").textContent || "").includes("From") && (document.getElementById("reply-bubble").textContent || "").includes("Note for the other chat"));
  console.log("sign-up, sign-in, chat, and relay passed");
  await browser.close();
}

writeConfig();
const mock = start(["-S", "127.0.0.1:8742", "-t", "tests", "tests/mock-xai.php"]);
const site = start(["-S", "127.0.0.1:8741", "-t", "public_html", "public_html/router.php"]);

async function waitMock() {
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    try {
      const probe = await fetch(MOCK + "/v1/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: [{ role: "user", content: "ping" }] }),
      });
      if (probe.ok) return;
    } catch (error) {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("mock not answering");
}

try {
  await waitFor(SITE + "/api/health");
  await waitMock();
  await apiTests();
  await browserTests();
  console.log("e2e ok");
} finally {
  site.kill("SIGTERM");
  mock.kill("SIGTERM");
}
