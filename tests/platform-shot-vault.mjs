export default async function vaultShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        op: "vault-put", token: auth, label: "Reef gate", value: "coral-secret", passphrase: "correct horse battery",
      }),
    });
    const data = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "vault-list", token: auth }),
    }).then((res) => res.json());
    const list = document.getElementById("vaultList");
    list.replaceChildren();
    (data.items || []).forEach((item) => {
      const row = document.createElement("li");
      row.textContent = item.label + " " + item.value + " ";
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Reveal";
      row.appendChild(button);
      list.appendChild(row);
    });
    document.getElementById("vaultCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator("#vaultList").waitFor({ state: "visible" });
  await shot(page, 1280, "vault");
  await shot(page, 390, "vault");
}
