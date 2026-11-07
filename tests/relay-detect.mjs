import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
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
    'supabase' => ['enabled' => false, 'project_ref' => 'wxvjajecvklfjxppawdx', 'url' => '', 'service_key' => ''],
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

async function waitHealth() {
  const deadline = Date.now() + 8000;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(SITE + "/api/health")).ok) return;
    } catch (error) {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("site not up");
}

async function visibleText(page, selector) {
  const locator = page.locator(selector);
  await locator.waitFor({ state: "visible" });
  const box = await locator.boundingBox();
  if (!box || box.width < 8 || box.height < 8) throw new Error(selector + " has no visible box");
  return locator.innerText();
}

async function signUp(page, email) {
  await page.click("#accountSignIn");
  await page.locator("#authModal").waitFor({ state: "visible" });
  await page.click("#authTabUp");
  await page.locator("#modalEmail").click();
  await page.locator("#modalEmail").pressSequentially(email, { delay: 10 });
  await page.locator("#modalPassword").click();
  await page.locator("#modalPassword").pressSequentially("reef-turtle-8", { delay: 10 });
  await page.click("#authModalSubmit");
  await page.waitForFunction((address) => (document.getElementById("accountEmail").title || "") === address, email);
}

async function openTools(page) {
  if (await page.locator("#drawer").isVisible()) return;
  if (!(await page.locator("#toolsToggle").isVisible())) {
    await page.evaluate(() => document.body.classList.remove("thread-open"));
  }
  await page.click("#toolsToggle");
  await page.locator("#drawer").waitFor({ state: "visible" });
}

async function detectCase(page, label) {
  await openTools(page);
  await page.click("#detectHardware");
  await page.locator("#drawer").waitFor({ state: "hidden" });
  const text = await visibleText(page, "#reply-bubble");
  for (const bit of ["browser", "CPU", "Memory", "GPU", "Recommended stack"]) {
    if (!new RegExp(bit, "i").test(text)) throw new Error(label + " detect missing " + bit + ": " + text);
  }
  console.log("detect visible", label);
}

async function openComposer(page) {
  if (await page.locator("#everyday").isVisible()) return;
  if (await page.locator("#sessionList button").count()) {
    await page.locator("#sessionList button").first().click();
    return;
  }
  await page.getByRole("button", { name: "New chat" }).click();
}

async function newChatCase(page) {
  await openComposer(page);
  await page.locator("#everyday").click();
  await page.locator("#everyday").pressSequentially("Hi", { delay: 15 });
  await page.click("#go");
  await page.waitForFunction(() => (document.getElementById("reply-bubble").textContent || "").includes("Hi"));
  const newChat = page.getByRole("button", { name: "New chat" });
  if (!(await newChat.isVisible()) && await page.locator("#backToList").isVisible()) {
    await page.click("#backToList");
  }
  const before = await page.locator("#sessionList button").count();
  await newChat.dblclick();
  await page.waitForFunction((n) => document.querySelectorAll("#sessionList button").length === n + 1, before);
  await page.waitForTimeout(500);
  const mid = await page.locator("#sessionList button").count();
  if (mid !== before + 1) throw new Error("one New Chat gesture created " + (mid - before) + " chats");
  if (!(await newChat.isVisible()) && await page.locator("#backToList").isVisible()) {
    await page.click("#backToList");
  }
  await newChat.click();
  await page.waitForFunction(() => document.activeElement && document.activeElement.id === "everyday");
  await page.waitForTimeout(400);
  const after = await page.locator("#sessionList button").count();
  if (after !== mid) throw new Error("New Chat on an empty chat created another");
  console.log("new chat stayed at one blank chat");
}

async function relayCase(page) {
  await openComposer(page);
  await page.locator("#everyday").click();
  await page.locator("#everyday").pressSequentially("Hello in chat one", { delay: 12 });
  await page.click("#go");
  await page.waitForFunction(() => (document.getElementById("reply-bubble").textContent || "").includes("Hello in chat one"));
  const firstTitle = await page.locator("#threadTitle").innerText();
  if (!(await page.locator("#newChat").isVisible()) && await page.locator("#backToList").isVisible()) {
    await page.click("#backToList");
  }
  await page.click("#newChat");
  await page.waitForFunction((prev) => document.getElementById("threadTitle").textContent !== prev, firstTitle);
  const secondTitle = await page.locator("#threadTitle").innerText();
  if (!(await page.locator("#everyday").isVisible()) && await page.locator("#sessionList button").first().isVisible()) {
    await page.locator("#sessionList button", { hasText: secondTitle }).click();
  }
  await page.locator("#everyday").click();
  await page.locator("#everyday").pressSequentially("Note for the other chat", { delay: 12 });
  if (!(await page.locator("#sendToChat").isVisible()) && await page.locator("#backToList").isVisible()) {
    await page.click("#backToList");
  }
  const arrow = page.getByRole("button", { name: "Send to chat" });
  const arrowBox = await arrow.boundingBox();
  const vp = page.viewportSize();
  if (!arrowBox || arrowBox.width < 8) throw new Error("sidebar Send to chat is not visible");
  if (vp.width >= 1000 && arrowBox.x > vp.width * 0.4) throw new Error("Send to chat is not in the sidebar");
  const appBefore = await page.locator("#app").boundingBox();
  await arrow.click();
  await page.locator("#relayOverlay").waitFor({ state: "visible" });
  if (await page.locator("#drawer").isVisible()) throw new Error("Send to chat opened the tools drawer");
  const appAfter = await page.locator("#app").boundingBox();
  if (Math.abs(appBefore.y - appAfter.y) > 2 || Math.abs(appBefore.height - appAfter.height) > 2) {
    throw new Error("Send to chat shifted the chat layout");
  }
  await page.locator("#relayTarget").waitFor({ state: "visible" });
  const destination = await page.locator("#relayTarget option:checked").innerText();
  if (!destination || destination === secondTitle) throw new Error("relay destination defaulted wrong: " + destination);
  await page.locator("#relayOverlay").getByRole("button", { name: "Send" }).click();
  await page.locator("#relayOverlay").waitFor({ state: "hidden" });
  const sent = await visibleText(page, "#reply-bubble");
  if (!sent.includes("Sent to " + destination)) throw new Error("missing confirmation: " + sent);
  if (!sent.includes("Note for the other chat")) throw new Error("confirmation dropped the note: " + sent);
  if (!(await page.locator("#sessionList").isVisible()) && await page.locator("#backToList").isVisible()) {
    await page.click("#backToList");
  }
  await page.locator("#sessionList button", { hasText: destination }).click();
  await page.waitForFunction((title) => (document.getElementById("reply-bubble").textContent || "").includes("From " + title), secondTitle);
  const from = await visibleText(page, "#reply-bubble");
  if (!from.includes("From " + secondTitle)) throw new Error("destination missing from-line: " + from);
  if (!from.includes("Note for the other chat")) throw new Error("destination dropped the note: " + from);
  const tools = page.getByRole("button", { name: "Tools" });
  if (!(await tools.isVisible()) && await page.locator("#backToList").isVisible()) await page.click("#backToList");
  const yBefore = (await page.locator("#app").boundingBox()).y;
  await tools.click();
  const yAfter = (await page.locator("#app").boundingBox()).y;
  if (Math.abs(yBefore - yAfter) > 2) throw new Error("Tools panel shifted the layout");
  await page.evaluate(() => { document.getElementById("drawer").hidden = true; });
  console.log("relay visible", secondTitle, "->", destination);
}

writeConfig();
const mock = start(["-S", "127.0.0.1:8742", "-t", "tests", "tests/mock-xai.php"]);
const site = start(["-S", "127.0.0.1:8741", "-t", "public_html", "public_html/router.php"]);
const browser = await chromium.launch({ channel: "chrome", headless: true });

try {
  await waitHealth();
  for (const [width, height] of [[1280, 800], [390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height } });
    page.on("pageerror", (error) => { throw error; });
    await page.goto(SITE + "/", { waitUntil: "domcontentloaded" });
    await detectCase(page, "signed-out " + width);
    const email = `relay-${width}-${Date.now()}@simkosi.test`;
    await signUp(page, email);
    await newChatCase(page);
    await relayCase(page);
    await detectCase(page, "signed-in " + width);
    await page.close();
  }
  console.log("relay and detect ok");
} finally {
  await browser.close();
  site.kill("SIGTERM");
  mock.kill("SIGTERM");
}
