export default async function paywallShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    for (let i = 1; i <= 5; i++) {
      await fetch("/api/simco/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "free " + i, token: auth, voice: i === 5 }),
      });
    }
  }, token);
  if (!(await page.locator("#everyday").isVisible()) && await page.locator("#sessionList button").count()) {
    await page.locator("#sessionList button").first().click();
  }
  await page.locator("#everyday").fill("one more please");
  await page.click("#go");
  await page.locator("#paywallCard").waitFor({ state: "visible" });
  await page.waitForFunction(() => (document.getElementById("paywallBuy").textContent || "").includes("$9.99"));
  await shot(page, 1280, "paywall");
  await shot(page, 390, "paywall");
  await page.click("#paywallTrial");
  await page.waitForFunction(() => (document.getElementById("paywallNote").textContent || "").includes("Nothing was charged"));
  await page.click("#paywallClose");
  if (!(await page.locator("#usageOpen").isVisible())) {
    if (!(await page.locator("#toolsToggle").isVisible()) && await page.locator("#backToList").isVisible()) {
      await page.click("#backToList");
    }
    await page.click("#toolsToggle");
  }
  await page.locator("#usageOpen").click();
  await page.locator("#usagePage").waitFor({ state: "visible" });
  await page.waitForFunction(() => (document.getElementById("usageSummary").textContent || "").includes("messages"));
  await shot(page, 1280, "usage");
  await shot(page, 390, "usage");
}
