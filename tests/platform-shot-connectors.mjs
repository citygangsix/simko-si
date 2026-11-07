export default async function connectorShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    const data = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "connectors", token: auth }),
    }).then((res) => res.json());
    const list = document.getElementById("connectorList");
    list.replaceChildren();
    (data.connectors || []).forEach((row) => {
      const item = document.createElement("li");
      item.textContent = row.ready ? row.name + " · " + row.scope : row.name + " is hidden until its client id is set.";
      list.appendChild(item);
    });
    document.getElementById("connectorCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator("#connectorList").waitFor({ state: "visible" });
  await shot(page, 1280, "connectors");
  await shot(page, 390, "connectors");
}
