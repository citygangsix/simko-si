export default async function searchShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    const data = await fetch("/api/simco/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "Where do sea turtles nest?", token: auth }),
    }).then((res) => res.json());
    const list = document.getElementById("searchSources");
    list.replaceChildren();
    (data.sources || []).forEach((url) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = url;
      link.textContent = url;
      item.appendChild(link);
      list.appendChild(item);
    });
    document.getElementById("searchCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator("#searchSources a").waitFor({ state: "visible" });
  await shot(page, 1280, "search");
  await shot(page, 390, "search");
}
