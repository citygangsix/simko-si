export default async function shareShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    const data = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "share-lifebook", token: auth }),
    }).then((res) => res.json());
    document.getElementById("shareUrl").textContent = data.share.url;
    document.getElementById("shareRevoke").hidden = false;
    document.getElementById("shareCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
    window.__sharePath = "/api/share?token=" + data.share.token;
  }, token);
  await page.locator("#shareUrl").waitFor({ state: "visible" });
  await shot(page, 1280, "share");
  await shot(page, 390, "share");
  const path = await page.evaluate(() => window.__sharePath);
  await page.goto(page.url().replace(/\/$/, "") + path);
  await page.locator("h1").waitFor({ state: "visible" });
  await shot(page, 1280, "report");
  await shot(page, 390, "report");
}
