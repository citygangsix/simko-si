// Real mouse-and-keyboard check of the in-chat Yes/No approval cards against a local php -S site with a mocked
// xAI and a fake MCP server. Clicks Yes and No on each card type, checks the chip and the result, saves screenshots.
// Usage: node tests/approval-cards-ui.mjs [outDir]
import { spawn, execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";

let chromium;
try { ({ chromium } = await import("playwright")); } catch (e) {
  ({ chromium } = await import(process.env.PLAYWRIGHT_MODULE || "/workspace/flagship/node_modules/playwright/index.mjs"));
}
const ROOT = new URL("..", import.meta.url).pathname.replace(/\/$/, "");
const OUT = process.argv[2] || "/workspace/simkosi-ops/p0-backend/approval-shots";
const PORT = 8860, MOCK = 8861, MCP = 8862;
const SITE = `http://127.0.0.1:${PORT}`;
const privateDir = `/tmp/simko-cards-ui-${process.pid}`;
mkdirSync(`${privateDir}/data`, { recursive: true });
mkdirSync(OUT, { recursive: true });
const config = {
  xai_api_key: "xai-local-mock", xai_base_url: `http://127.0.0.1:${MOCK}/v1`, model: "grok-4.7",
  mail_mode: "dev", dev_codes_in_reply: true, site_url: "https://simkosi.com", family_ui: false, max_input_chars: 8000,
  platform: { approvals: true, tasks: true, mcp: true, search: true, paywall: false },
  owner_access: { emails: [], user_ids: [1] },
  connectors: { token_key: "test-only-connector-key-ui" },
  spend_caps: { owner_daily_usd: 5.0, user_daily_usd: 1.0, site_daily_usd: 10.0, timezone: "America/New_York" },
  // Test-mode Stripe only, pointed at a closed port: the cards never call Stripe.
  stripe: { secret_key: "sk_test_localonly4242", account_id: "acct_TEST9876", price_id: "price_test_1", api_base: "http://127.0.0.1:9" },
  mcp: { allowed_hosts: ["127.0.0.1", "localhost"], allow_http: true, allow_private: true, paid_hosts: { localhost: 0.05 } },
};
writeFileSync(`${privateDir}/config.php`, `<?php\ndeclare(strict_types=1);\nreturn json_decode('${JSON.stringify(config).replace(/'/g, "\\'")}', true);\n`);
const env = { ...process.env, SIMKOSI_PRIVATE: privateDir };
for (const k of ["STRIPE_SECRET_KEY", "STRIPE_RESTRICTED_KEY", "STRIPE_PRICE_ID", "STRIPE_API_BASE", "STRIPE_WEBHOOK_SECRET"]) delete env[k];
const procs = [];
function start(args, cwd) {
  const child = spawn("php", args, { cwd, env, stdio: ["ignore", "ignore", "ignore"] });
  procs.push(child);
  return child;
}
start(["-S", `127.0.0.1:${MOCK}`, "-t", "tests", "tests/mock-xai.php"], ROOT);
start(["-S", `127.0.0.1:${MCP}`, "fake-mcp.php"], `${ROOT}/tests`);
start(["-S", `127.0.0.1:${PORT}`, "-t", "public_html", "public_html/router.php"], ROOT);
async function waitUp(url) {
  const end = Date.now() + 10000;
  while (Date.now() < end) { try { const r = await fetch(url); if (r.status < 500) return; } catch (e) {} await new Promise((r) => setTimeout(r, 120)); }
  throw new Error("not up " + url);
}
const sql = (q) => execFileSync("php", ["-r", `$d = new PDO('sqlite:${privateDir}/data/simko.sqlite'); $d->exec(${JSON.stringify(q)}); echo 'ok';`]).toString();
const results = [];
const shots = [];
function check(ok, label) { results.push((ok ? "PASS " : "FAIL ") + label); if (!ok) throw new Error("FAIL " + label); }

const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--mute-audio"] });
try {
  await waitUp(`${SITE}/api/health`);
  await waitUp(`http://127.0.0.1:${MCP}/nothing`);
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  page.on("pageerror", (e) => results.push("PAGE ERROR " + e.message));
  async function shot(name, width = 1280) {
    await page.setViewportSize({ width, height: width < 500 ? 844 : 860 });
    if (width < 500) await page.evaluate(() => document.body.classList.add("thread-open"));
    const path = `${OUT}/${name}-${width}.png`;
    await page.screenshot({ path });
    shots.push(path);
    if (width !== 1280) await page.setViewportSize({ width: 1280, height: 860 });
  }
  // Sign up with the real form (keyboard typing).
  const email = `cards-${Date.now()}@simkosi.test`;
  await page.goto(`${SITE}/`, { waitUntil: "domcontentloaded" });
  await page.click("#accountSignIn");
  await page.click("#authTabUp");
  await page.locator("#modalEmail").click();
  await page.keyboard.type(email, { delay: 8 });
  await page.locator("#modalPassword").click();
  await page.keyboard.type("reef-turtle-8", { delay: 8 });
  const signupResp = page.waitForResponse((r) => r.url().includes("/api/auth") && (r.request().postData() || "").includes('"signup"'));
  await page.click("#authModalSubmit");
  const signup = await (await signupResp).json();
  if (signup.dev_token) await page.evaluate(async (code) => { await fetch("/api/auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "confirm-email", confirm_token: code, token: sessionStorage.getItem("podcoderToken") || "" }) }); }, signup.dev_token);
  await page.locator("#authModal").waitFor({ state: "hidden" });
  const token = signup.token;
  const api = (body) => page.evaluate(async ({ body, token }) => (await fetch("/api/platform", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, token }) })).json(), { body, token });

  async function say(text) {
    const box = page.locator("#everyday");
    await box.click();
    await page.keyboard.type(text, { delay: 6 });
    await page.keyboard.press("Enter");
  }
  async function cardFor(action, nth = 0) {
    const card = page.locator(`#thread .approvalCard[data-action="${action}"]:not(.approvalCardDone)`).nth(nth);
    await card.waitFor({ state: "visible", timeout: 20000 });
    const id = await card.getAttribute("data-approval-id");
    return page.locator(`#thread .approvalCard[data-approval-id="${id}"]`);
  }
  async function chipOf(card, re) {
    await card.locator(".approvalCardChip").waitFor({ state: "visible", timeout: 20000 });
    await page.waitForFunction(({ el, src }) => new RegExp(src).test(el.textContent || ""), { el: await card.locator(".approvalCardChip").elementHandle(), src: re.source }, { timeout: 20000 });
    return (await card.locator(".approvalCardChip").innerText()).trim();
  }
  async function clickButton(card, cls) {
    const b = await card.locator(cls).boundingBox();
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 4 });
    await page.mouse.down(); await page.mouse.up();
  }

  // 1. task-start: Yes
  await say("TASKCREATE every morning give me the news");
  let card = await cardFor("task-start");
  const t1 = await card.innerText();
  check(/Start scheduled task 'Morning news'/.test(t1) && /Cost: About \$0\.020 per run/.test(t1) && /left/.test(t1) && /Where: Every day at 7:15 AM/.test(t1), "task-start card shows title, what, cost + cap left, where");
  await shot("1-task-start-card");
  await shot("1-task-start-card", 390);
  await clickButton(card, ".approvalYes");
  let chip = await chipOf(card, /^Approved, ran:/);
  check(/Approved, ran: Started 'Morning news'/.test(chip), "task-start Yes -> chip: " + chip);
  const tasks = await api({ op: "task-list" });
  check(tasks.tasks.length === 1 && tasks.tasks[0].enabled === true, "task exists and is on after Yes");
  await shot("2-task-start-approved");

  // 2. task-start: No
  await say("TASKCREATE every morning again please");
  card = await cardFor("task-start");
  await clickButton(card, ".approvalNo");
  chip = await chipOf(card, /^Declined/);
  check(chip === "Declined, nothing ran", "task-start No -> chip: " + chip);
  check((await api({ op: "task-list" })).tasks.length === 1, "No created nothing");
  await shot("3-task-start-declined");

  // 3. paywall-on: No, then Yes
  await say("PAYWALLON turn the paywall on please");
  card = await cardFor("paywall-on");
  const p1 = await card.innerText();
  check(/Price: \$9\.99\/month/.test(p1) && /Free messages: 5/.test(p1) && /Stripe: test mode, account ending 9876/.test(p1) && /Who: 0 non-owner accounts/.test(p1) && !/sk_test/.test(p1), "paywall card facts (price, 5 free, Stripe test + last 4, who)");
  await shot("4-paywall-card");
  await clickButton(card, ".approvalNo");
  chip = await chipOf(card, /^Declined/);
  check(chip === "Declined, nothing ran", "paywall No -> chip");
  await say("PAYWALLON ok turn the paywall on now");
  card = await cardFor("paywall-on");
  await clickButton(card, ".approvalYes");
  chip = await chipOf(card, /^Approved, ran:/);
  check(/Paywall on: \$9\.99\/month after 5 free messages \(Stripe test\)/.test(chip), "paywall Yes -> chip: " + chip);
  await shot("5-paywall-approved");
  await api({ op: "paywall-set", on: false });

  // 4. mcp-token-share: two token connectors; No on one, Yes on the other.
  await api({ op: "mcp-save", label: "Locked notes", url: `http://127.0.0.1:${MCP}/mcp-auth`, bearer_token: "mcp-test-token" });
  await api({ op: "mcp-save", label: "Team notes", url: `http://127.0.0.1:${MCP}/mcp-auth`, bearer_token: "mcp-test-token" });
  await say("find my grout note");
  const lockedCard = page.locator('#thread .approvalCard[data-action="mcp-token-share"]', { hasText: "Locked notes" });
  const teamCard = page.locator('#thread .approvalCard[data-action="mcp-token-share"]', { hasText: "Team notes" });
  await lockedCard.waitFor({ state: "visible", timeout: 20000 });
  await teamCard.waitFor({ state: "visible" });
  check(/To read from Locked notes, Simko SI sends your Locked notes login to xAI, which makes the request for you\./.test(await lockedCard.innerText()), "token card text");
  await shot("6-token-cards");
  await clickButton(lockedCard, ".approvalNo");
  chip = await chipOf(lockedCard, /^Declined/);
  check(chip === "Declined, nothing ran", "token No -> chip");
  await clickButton(teamCard, ".approvalYes");
  chip = await chipOf(teamCard, /^Approved, ran:/);
  check(chip === "Approved, ran: Team notes read tools on", "token Yes -> chip: " + chip);
  const reply = await page.locator("#reply-bubble").innerText();
  const servers = (await api({ op: "mcp-list" })).servers;
  const locked = servers.find((s) => s.label === "Locked notes"), team = servers.find((s) => s.label === "Team notes");
  check(reply.includes(`simko_s${team.id}=get_note|search_notes+auth`) && !reply.includes(`simko_s${locked.id}`), "after Yes only the consented connector's read tools go to Grok: " + reply.slice(0, 160));
  await shot("7-token-decided");

  // 5. mcp-spend: paid connector read (Yes), paid write combined card (No).
  const paid = await api({ op: "mcp-save", label: "Paid notes", url: `http://localhost:${MCP}/mcp` });
  await say("MCPREAD look for grout in paid notes");
  card = await cardFor("mcp-spend");
  const s1 = await card.innerText();
  check(/Read from Paid notes \(paid\): search_notes/.test(s1) && /Cost: About \$0\.050 for this call/.test(s1) && /Costs money/.test(s1), "mcp-spend card (cost + cap left + where)");
  await shot("8-spend-card");
  await clickButton(card, ".approvalYes");
  chip = await chipOf(card, /^Approved, ran:/);
  check(/Paid notes · search_notes \(\$0\.05\)/.test(chip), "spend Yes -> chip: " + chip);
  await api({ op: "mcp-tools", server_id: paid.server.id, tools: { create_note: true } });
  await say("MCPWRITE add a note to buy grout");
  card = await cardFor("mcp-spend");
  const s2 = await card.innerText();
  check(/Change something in Paid notes \(paid\): create_note/.test(s2) && /Changes something/.test(s2) && /Costs money/.test(s2), "paid write is one combined card");
  await shot("9-spend-write-combined");
  await clickButton(card, ".approvalNo");
  chip = await chipOf(card, /^Declined/);
  check(chip === "Declined, nothing ran", "combined card No -> chip");

  // 6. Pending card re-renders on reopen; expired after 24 h shows "Expired, ask again".
  await say("TASKCREATE every morning one more");
  card = await cardFor("task-start");
  const pendingId = await card.getAttribute("data-approval-id");
  const firstChat = await page.evaluate(() => document.querySelector("#sessionList button[aria-pressed='true']")?.dataset.id || "");
  await page.click("#newChat");
  await page.waitForFunction((id) => !document.querySelector(`#thread .approvalCard[data-approval-id="${id}"]`), pendingId);
  await page.locator(`#sessionList button[data-id="${firstChat}"]`).click();
  const reopened = page.locator(`#thread .approvalCard[data-approval-id="${pendingId}"]`);
  await reopened.waitFor({ state: "visible", timeout: 20000 });
  check(await reopened.locator(".approvalYes").isVisible(), "pending card re-rendered on chat reopen with Yes/No");
  await shot("10-reopened-pending");
  sql(`UPDATE approvals SET created_at = ${Math.floor(Date.now() / 1000) - 90000} WHERE id = ${Number(pendingId)}`);
  await page.click("#newChat");
  await page.locator(`#sessionList button[data-id="${firstChat}"]`).click();
  const expired = page.locator(`#thread .approvalCard[data-approval-id="${pendingId}"]`);
  await expired.waitFor({ state: "visible", timeout: 20000 });
  chip = await chipOf(expired, /Expired/);
  check(chip === "Expired, ask again" && !(await expired.locator(".approvalYes").isVisible()), "expired card shows 'Expired, ask again' with no buttons");
  await shot("11-expired");
  check(!results.some((r) => r.startsWith("PAGE ERROR")), "no page errors");
} finally {
  await browser.close();
  procs.forEach((p) => p.kill("SIGTERM"));
  console.log(results.join("\n"));
  console.log(shots.join("\n"));
}
