export default async function callShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    const data = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "call-status", token: auth }),
    }).then((res) => res.json());
    document.getElementById("callReason").textContent = data.reason;
    document.getElementById("callStart").disabled = true;
    document.getElementById("callCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator("#callStart").waitFor({ state: "visible" });
  const disabled = await page.locator("#callStart").isDisabled();
  if (!disabled) throw new Error("call button should stay disabled");
  await shot(page, 1280, "calls");
  await shot(page, 390, "calls");
}
