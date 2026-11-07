export default async function approvalShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    const headers = { "Content-Type": "application/json" };
    const created = async (title) => {
      const data = await fetch("/api/sessions", { method: "POST", headers, body: JSON.stringify({ op: "create", title, token: auth }) }).then((res) => res.json());
      return data.session.id;
    };
    const from = await created("From chat");
    const to = await created("To chat");
    window.__relay = { from, to };
  }, token);
  const ids = await page.evaluate(() => window.__relay);
  await page.evaluate(async ({ auth, ids }) => {
    const data = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        op: "relay",
        token: auth,
        from_session_id: ids.from,
        to_session_id: ids.to,
        text: "Send the bedtime note",
      }),
    }).then((res) => res.json());
    window.__approval = data.approval;
  }, { auth: token, ids });
  await page.evaluate(() => {
    const card = document.getElementById("approvalCard");
    const summary = document.getElementById("approvalSummary");
    summary.textContent = window.__approval.summary;
    document.getElementById("auditList").innerHTML = "<li>Nothing has been approved or declined yet.</li>";
    card.hidden = false;
    document.getElementById("platformStage").hidden = false;
  });
  await page.locator("#approvalYes").waitFor({ state: "visible" });
  await shot(page, 1280, "approval");
  await shot(page, 390, "approval");
}
