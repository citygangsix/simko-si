export default async function storeShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    const data = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "store-steps", token: auth }),
    }).then((res) => res.json());
    const list = document.getElementById("storeSteps");
    list.replaceChildren();
    (data.steps || []).forEach((step) => {
      const item = document.createElement("li");
      item.textContent = step;
      list.appendChild(item);
    });
    document.getElementById("storeCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator("#storeSteps li").first().waitFor({ state: "visible" });
  await shot(page, 1280, "store");
  await shot(page, 390, "store");
}
