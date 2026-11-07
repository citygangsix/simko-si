import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const SITE = "http://127.0.0.1:8761";
const MOCK = "http://127.0.0.1:8762";

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

const FAKE_MEDIA = () => {
  const Real = window.AudioContext || window.webkitAudioContext;
  navigator.mediaDevices = navigator.mediaDevices || {};
  navigator.mediaDevices.getUserMedia = async () => {
    const ctx = new Real();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    gain.gain.value = 0.25;
    osc.frequency.value = 440;
    const dest = ctx.createMediaStreamDestination();
    osc.connect(gain);
    gain.connect(dest);
    osc.start();
    const stream = dest.stream;
    stream.getTracks().forEach((track) => {
      const stop = track.stop.bind(track);
      track.stop = () => {
        window.__micStopped = true;
        stop();
      };
    });
    return stream;
  };
  class FakeSR {
    start() { window.__liveStarts = (window.__liveStarts || 0) + 1; }
    stop() {}
    abort() {}
  }
  window.SpeechRecognition = FakeSR;
  window.webkitSpeechRecognition = FakeSR;
};

writeConfig();
const mock = start(["-S", "127.0.0.1:8762", "-t", "tests", "tests/mock-xai.php"]);
const site = start(["-S", "127.0.0.1:8761", "-t", "public_html", "public_html/router.php"]);
mkdirSync("/opt/cursor/artifacts", { recursive: true });

const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--mute-audio", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
});

try {
  await waitHealth();
  const context = await browser.newContext({ viewport: { width: 420, height: 900 } });
  await context.addInitScript(FAKE_MEDIA);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const email = `voice-${Date.now()}@simkosi.test`;
  await page.goto(SITE + "/", { waitUntil: "domcontentloaded" });
  await page.click("#accountSignIn");
  await page.click("#authTabUp");
  await page.locator("#modalEmail").fill(email);
  await page.locator("#modalPassword").fill("reef-turtle-8");
  await page.click("#authModalSubmit");
  await page.waitForFunction((address) => (document.getElementById("accountEmail").title || "") === address, email);
  await page.locator("#chatEmpty").waitFor({ state: "visible" });
  if ((await page.locator("#listTitle").innerText()) !== "Chats") throw new Error("list title missing");
  await page.getByRole("button", { name: "New chat" }).click();
  await page.locator("#everyday").waitFor({ state: "visible" });
  const goLabel = await page.locator("#go").getAttribute("aria-label");
  if (goLabel !== "Start voice conversation") throw new Error("empty button should be the wave, got " + goLabel);
  await page.screenshot({ path: "/opt/cursor/artifacts/simkosi-voice-off-420.png" });

  await page.click("#go");
  await page.locator("#liveVoice").waitFor({ state: "visible" });
  await page.waitForFunction(() => (document.getElementById("liveVoiceState").textContent || "") === "Listening");
  try {
    await page.waitForFunction(() => Number((document.getElementById("liveBars") || {}).dataset.tick || 0) > 2, null, { timeout: 15000 });
  } catch (error) {
    const info = await page.evaluate(() => ({
      tick: document.getElementById("liveBars") && document.getElementById("liveBars").dataset.tick,
      phase: document.getElementById("liveVoice") && document.getElementById("liveVoice").dataset.phase,
      text: document.getElementById("liveVoiceState") && document.getElementById("liveVoiceState").textContent,
      live: !!(window.simcoVoice && window.simcoVoice.state && window.simcoVoice.state.live),
      phaseState: window.simcoVoice && window.simcoVoice.state && window.simcoVoice.state.livePhase,
      started: window.__barsStarted || 0,
      raf: typeof requestAnimationFrame
    }));
    console.log("VOICE DEBUG " + JSON.stringify(info));
    console.log("PAGE ERRORS " + errors.join(" | "));
    throw error;
  }
  const heights = await page.locator("#liveBars i").evaluateAll((nodes) => nodes.map((node) => node.style.height));
  if (heights.filter(Boolean).length < 5) throw new Error("wave bars did not animate: " + heights.join(","));
  await page.screenshot({ path: "/opt/cursor/artifacts/simkosi-voice-on-420.png" });

  await page.click("#go");
  await page.locator("#liveVoice").waitFor({ state: "hidden" });
  await page.waitForFunction(() => window.__micStopped === true);
  const tracks = await page.evaluate(() => window.__micStopped === true);
  if (!tracks) throw new Error("mic tracks were not stopped");

  await page.locator("#everyday").fill("typed from the keys");
  await page.waitForFunction(() => document.getElementById("go").getAttribute("aria-label") === "Send");
  await page.locator("#everyday").press("Enter");
  await page.waitForFunction(() => (document.getElementById("reply-bubble").textContent || "").includes("typed from the keys"));
  if (await page.locator("#liveVoice").isVisible()) throw new Error("typed send restarted live voice");
  console.log("live voice toggles, and typed send still works");

  const token = await page.evaluate(() => sessionStorage.getItem("podcoderToken"));
  const names = ["Alpha reef", "Beta reef", "Gamma reef", "Delta reef", "Epsilon reef"];
  for (const title of names) {
    const response = await page.evaluate(async ({ token, title }) => {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ op: "create", title, token })
      });
      return res.status;
    }, { token, title });
    if (response !== 200) throw new Error("create " + title + " status " + response);
  }
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.locator("#sessionList button").nth(4).waitFor({ state: "attached" });
  const loaded = await page.locator("#sessionList button").count();
  if (loaded < names.length) throw new Error("reload showed " + loaded + " chats");
  await page.locator("#sessionList button").first().click();
  await page.locator("#backToList").waitFor({ state: "visible" });
  await page.click("#backToList");
  await page.waitForFunction(() => document.body.dataset.listReady === "1");
  await page.locator("#listTitle").waitFor({ state: "visible" });
  const titles = await page.locator("#sessionList button").allInnerTexts();
  for (const name of names) {
    if (!titles.some((row) => row.includes(name))) throw new Error("Back list missing " + name + " in " + titles.join(" | "));
  }
  await page.screenshot({ path: "/opt/cursor/artifacts/simkosi-chats-back-420.png" });
  await page.click("#searchChats");
  await page.locator("#chatSearch").fill("Gamma");
  await page.waitForFunction(() => {
    const rows = [...document.querySelectorAll("#sessionList button")].map((button) => button.textContent || "");
    return rows.length === 1 && rows[0].includes("Gamma");
  });
  await page.locator("#chatSearch").fill("");
  await page.waitForFunction((need) => document.querySelectorAll("#sessionList button").length >= need, names.length);
  if (errors.length) throw new Error(errors.join(" | "));
  console.log("back opens every saved chat");
  await context.close();
} finally {
  await browser.close();
  site.kill("SIGTERM");
  mock.kill("SIGTERM");
}
