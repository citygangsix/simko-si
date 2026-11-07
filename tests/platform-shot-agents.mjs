export default async function agentShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    const headers = { "Content-Type": "application/json" };
    for (const agent of [
      { name: "Reef", persona: "Warm and brief" },
      { name: "Tide", persona: "Careful with facts" },
    ]) {
      await fetch("/api/platform", { method: "POST", headers, body: JSON.stringify({ op: "create-agent", token: auth, ...agent }) });
    }
    const data = await fetch("/api/platform", { method: "POST", headers, body: JSON.stringify({ op: "agents", token: auth }) }).then((res) => res.json());
    const board = document.getElementById("agentPanes");
    board.replaceChildren();
    (data.agents || []).forEach((agent) => {
      const pane = document.createElement("article");
      pane.className = "agentPane";
      pane.innerHTML = "<h3></h3><p></p>";
      pane.querySelector("h3").textContent = agent.name;
      pane.querySelector("p").textContent = agent.persona;
      board.appendChild(pane);
    });
    document.getElementById("agentBoard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator(".agentPane").nth(1).waitFor({ state: "visible" });
  await shot(page, 1280, "agents");
  await shot(page, 390, "agents");
}
