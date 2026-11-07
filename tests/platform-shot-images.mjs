export default async function imageShot(page, shot, token) {
  await page.evaluate(async (auth) => {
    const data = await fetch("/api/platform", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ op: "imagine", token: auth, prompt: "A sea turtle over the reef" }),
    }).then((res) => res.json());
    const grid = document.getElementById("imageGrid");
    grid.replaceChildren();
    (data.images || []).forEach((row) => {
      const img = document.createElement("img");
      img.alt = row.prompt;
      img.src = row.url;
      grid.appendChild(img);
    });
    document.getElementById("imagePrompt").value = "A sea turtle over the reef";
    document.getElementById("imageCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  }, token);
  await page.locator("#imageCard").waitFor({ state: "visible" });
  await shot(page, 1280, "image");
  await shot(page, 390, "image");
}
