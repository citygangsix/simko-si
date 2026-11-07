export default async function browseShot(page, shot) {
  await page.evaluate(() => {
    document.getElementById("browseUrl").value = "https://example.com/notes";
    document.getElementById("browseText").textContent = "This reads one allow-listed page. Full browser automation is not available on shared hosting.";
    document.getElementById("browseCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  });
  await page.locator("#browseTitle").waitFor({ state: "visible" });
  await shot(page, 1280, "browse");
  await shot(page, 390, "browse");
}
