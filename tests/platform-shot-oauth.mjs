export default async function oauthShot(page, shot) {
  await page.evaluate(() => {
    document.getElementById("googleSignIn").hidden = false;
    document.getElementById("appleSignIn").hidden = false;
    document.getElementById("oauthCard").hidden = false;
    document.getElementById("platformStage").hidden = false;
  });
  await page.locator("#googleSignIn").waitFor({ state: "visible" });
  await shot(page, 1280, "oauth");
  await shot(page, 390, "oauth");
}
