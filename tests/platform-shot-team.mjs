export default async function teamShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    const agent = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "create-agent", token: auth, name: "Reef", persona: "Warm and brief" }),
    }).then((res) => res.json());
    const link = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "publish-template", token: auth, agent_id: agent.agent.id }),
    }).then((res) => res.json());
    document.getElementById("teamNote").textContent = "Template: " + link.template.url;
    document.getElementById("teamCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator("#teamNote").waitFor({ state: "visible" });
  await shot(page, 1280, "team");
  await shot(page, 390, "team");
}
