import { chromium } from "playwright";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 900, height: 700 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto("http://localhost:5173");
  const dialog = page.getByRole("dialog", { name: "Passcode" });
  await dialog.waitFor({ timeout: 10000 });
  console.log("• passcode sheet shown on load");
  await page.getByRole("textbox", { name: "Passcode" }).fill("wrong-one");
  await page.getByRole("button", { name: /unlock/i }).click();
  await page.getByPlaceholder("Wrong passcode").waitFor({ timeout: 10000 });
  console.log("• wrong passcode -> asked again");
  await page.getByRole("textbox", { name: "Passcode" }).fill("test-pass");
  await page.getByRole("button", { name: /unlock/i }).click();
  await page.getByText("Biology Midterm 2").waitFor({ timeout: 10000 });
  console.log("• correct passcode -> reviewers listed");
  await page.reload();
  await page.getByText("Biology Midterm 2").waitFor({ timeout: 10000 });
  const shown = await dialog.isVisible().catch(() => false);
  if (shown) throw new Error("asked again after reload");
  console.log("• remembered after reload");
  await page.screenshot({ path: "../design/screenshots/12-passcode.png" });
  if (errors.length) throw new Error(errors.join("\n"));
  console.log("OK");
} catch (e) { console.error("FAILED:", e.message); process.exitCode = 1; }
finally { await browser.close(); }
