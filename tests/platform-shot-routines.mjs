export default async function routineShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "save-routine", token: auth, kind: "homework", hour: 16, minute: 30 }),
    });
    const data = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "routines", token: auth }),
    }).then((res) => res.json());
    const list = document.getElementById("routineList");
    list.replaceChildren();
    (data.routines || []).forEach((row) => {
      const item = document.createElement("li");
      item.textContent = row.label + " at " + String(row.hour).padStart(2, "0") + ":" + String(row.minute).padStart(2, "0");
      list.appendChild(item);
    });
    document.getElementById("routineCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator("#routineList").waitFor({ state: "visible" });
  await shot(page, 1280, "routines");
  await shot(page, 390, "routines");
}
