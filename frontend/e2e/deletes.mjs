// Browser check: deleting an exam set, and removing a file with confirmation.
// Run with both servers up: node e2e/deletes.mjs  (APP_URL / APP_PASSCODE optional)
import { resolve } from "node:path";

import { chromium } from "playwright";

const APP = process.env.APP_URL ?? "http://localhost:5173";
const PASSCODE = process.env.APP_PASSCODE ?? "";
const SAMPLES = resolve("../backend/samples");
const SHOTS = resolve(process.env.SHOTS_DIR ?? "../design/screenshots");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 820 } });
const errors = [];
let unlocked = !PASSCODE;
page.on("console", (m) => { if (m.type() === "error" && (unlocked || !/401/.test(m.text()))) errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(e.message));
const step = (s) => console.log("•", s);

try {
  await page.goto(APP);
  if (PASSCODE) {
    await page.getByRole("dialog", { name: "Passcode" }).waitFor({ timeout: 20_000 });
    await page.getByRole("textbox", { name: "Passcode" }).fill(PASSCODE);
    await page.getByRole("button", { name: /unlock/i }).click();
    unlocked = true;
  }
  step("create a reviewer with two files");
  await page.getByRole("button", { name: /new/i }).click();
  await page.locator('input[type="file"]').setInputFiles([
    `${SAMPLES}/Lesson 3 - Photosynthesis.pptx`,
    `${SAMPLES}/Lesson 4 - Cellular Respiration.pdf`,
  ]);
  await page.waitForFunction(
    () => [...document.querySelectorAll(".up span:last-child")].length === 2 &&
      [...document.querySelectorAll(".up span:last-child")].every((s) => /Ready|reused/.test(s.textContent)),
    null, { timeout: 300_000 },
  );
  await page.getByLabel("Reviewer name").fill("Delete test");
  await page.getByRole("button", { name: "Create" }).click();
  await page.getByRole("heading", { name: "Delete test" }).waitFor();

  step("make an exam");
  const start = page.getByRole("button", { name: /start exam/i });
  await page.waitForFunction((el) => !el.disabled, await start.elementHandle(), { timeout: 60_000 });
  await start.click();
  await page.waitForFunction(() => /\/ \d+/.test(document.querySelector(".count-row .muted")?.textContent ?? ""));
  await page.getByLabel("Number of items").fill("4");
  await page.getByRole("button", { name: /^start$/i }).click();
  await page.waitForURL(/\/attempts\/[^/]+$/, { timeout: 300_000 });
  await page.getByRole("button", { name: /exit exam/i }).click();
  await page.getByRole("button", { name: /save/i }).click();
  await page.waitForURL(/\/reviewers\//);
  await page.locator(".r-exam-row").first().waitFor();
  const usedBefore = (await page.locator(".cov").textContent()).trim();
  step(`exam listed; coverage "${usedBefore}"`);

  step("delete exam: cancel keeps it");
  await page.getByRole("button", { name: /delete set 1/i }).click();
  await page.getByRole("dialog", { name: /delete set 1/i }).waitFor();
  await page.screenshot({ path: `${SHOTS}/13-delete-exam.png` });
  await page.getByRole("button", { name: "Cancel" }).click();
  if ((await page.locator(".r-exam-row").count()) !== 1) throw new Error("cancel removed the exam");

  step("delete exam: confirm removes it and frees its items");
  await page.getByRole("button", { name: /delete set 1/i }).click();
  await page.getByRole("dialog").getByRole("button", { name: /^delete$/i }).click();
  await page.getByText("No exams yet").waitFor({ timeout: 20_000 });
  await page.waitForFunction(() => /\b0\/\d+ reviewed/.test(document.querySelector(".cov")?.textContent ?? ""), null, { timeout: 20_000 });
  step(`coverage now "${(await page.locator(".cov").textContent()).trim()}"`);

  step("remove file: x opens a confirmation");
  const before = await page.locator(".r-file").count();
  await page.getByRole("button", { name: /remove lesson 3/i }).click();
  const dialog = page.getByRole("dialog", { name: "Delete file?" });
  await dialog.waitFor();
  await dialog.getByText("Lesson 3 - Photosynthesis.pptx").waitFor();
  await page.screenshot({ path: `${SHOTS}/14-delete-file.png` });
  await page.keyboard.press("Escape");
  if ((await page.locator(".r-file").count()) !== before) throw new Error("Escape removed the file");
  await page.getByRole("button", { name: /remove lesson 3/i }).click();
  await page.getByRole("dialog").getByRole("button", { name: /^delete$/i }).click();
  await page.waitForFunction((n) => document.querySelectorAll(".r-file").length === n - 1, before, { timeout: 20_000 });
  step("file removed");
  const lastX = page.getByRole("button", { name: /remove lesson 4/i });
  if (!(await lastX.isDisabled())) throw new Error("last file's x should be disabled");
  step("last file can't be removed (x disabled)");

  step("clean up: delete the reviewer");
  await page.getByRole("button", { name: /more options/i }).click();
  await page.getByRole("button", { name: /^delete$/i }).click();
  await page.getByRole("dialog").getByRole("button", { name: /delete/i }).click();
  await page.waitForURL((u) => new URL(u).pathname === "/");

  if (errors.length) { console.log("CONSOLE ERRORS:\n" + errors.join("\n")); process.exitCode = 1; }
  else console.log("OK — no console errors");
} catch (e) {
  console.error("FAILED:", e.message);
  await page.screenshot({ path: `${SHOTS}/zz-deletes-failure.png`, fullPage: true });
  if (errors.length) console.log("console:", errors.join("\n"));
  process.exitCode = 1;
} finally {
  await browser.close();
}
