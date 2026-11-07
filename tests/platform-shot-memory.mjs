export default async function memoryShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    await fetch("/api/simco/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "Remember that the reef is home.", token: auth }),
    });
    const data = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "memories", token: auth }),
    }).then((res) => res.json());
    const list = document.getElementById("memoryList");
    list.replaceChildren();
    (data.memories || []).forEach((row) => {
      const item = document.createElement("li");
      item.textContent = row.fact + " ";
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Delete";
      item.appendChild(button);
      list.appendChild(item);
    });
    document.getElementById("memoryCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator("#memoryList").waitFor({ state: "visible" });
  await shot(page, 1280, "memory");
  await shot(page, 390, "memory");
}
