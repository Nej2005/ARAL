// End-to-end click-through of the real app (frontend on :5173, backend on :8000, real Gemini).
// Run: node e2e/flow.mjs   — writes screenshots to ../design/screenshots/
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

import { chromium } from "playwright";

const APP = "http://localhost:5173";
const SAMPLES = resolve("../backend/samples");
const SHOTS = resolve("../design/screenshots");
mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, acceptDownloads: true });
const page = await ctx.newPage();
const consoleErrors = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));

const step = (s) => console.log("•", s);
const shot = async (name) => {
  await page.screenshot({ path: `${SHOTS}/${name}-desktop.png`, fullPage: true });
  const vp = page.viewportSize();
  await page.setViewportSize({ width: 390, height: 780 });
  await page.waitForTimeout(150);
  await page.screenshot({ path: `${SHOTS}/${name}-phone.png`, fullPage: false });
  await page.setViewportSize(vp);
};

try {
  step("home");
  await page.goto(APP);
  await page.getByRole("heading", { name: /reviewers/i }).waitFor();
  await shot("01-home-empty");

  step("new reviewer: upload two files");
  await page.getByRole("button", { name: /new/i }).click();
  await page.locator('input[type="file"]').setInputFiles([
    `${SAMPLES}/Lesson 3 - Photosynthesis.pptx`,
    `${SAMPLES}/Lesson 4 - Cellular Respiration.pdf`,
  ]);
  await page.locator(".up").nth(1).waitFor();
  await shot("02-new-reviewer");
  // wait until both rows say Ready / reused (real Gemini extraction can take a while)
  await page.waitForFunction(
    () => [...document.querySelectorAll(".up span:last-child")].every((s) => /Ready|reused/.test(s.textContent)),
    null, { timeout: 240_000 },
  );
  await page.getByLabel("Reviewer name").fill("Biology Midterm");
  await page.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(/\/reviewers\//);
  await page.getByRole("heading", { name: "Biology Midterm" }).waitFor();
  await page.getByRole("button", { name: /start exam/i }).waitFor({ state: "visible" });
  await page.waitForTimeout(500);
  await shot("03-reviewer");

  step("dark mode toggle");
  await page.getByRole("button", { name: /switch to (dark|light) mode/i }).click();
  const theme1 = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
  await shot(`04-reviewer-${theme1}`);
  await page.getByRole("button", { name: /switch to (dark|light) mode/i }).click();

  step("new exam sheet");
  const start = page.getByRole("button", { name: /start exam/i });
  await page.waitForFunction((el) => !el.disabled, await start.elementHandle(), { timeout: 30_000 });
  await start.click();
  await page.getByRole("dialog", { name: "New exam" }).waitFor();
  await page.waitForFunction(() => /\/ \d+/.test(document.querySelector(".count-row .muted")?.textContent ?? ""));
  await page.getByLabel("Number of items").fill("5");
  await page.getByText("Choose slides or topics").click();
  await page.locator(".chip").first().waitFor();
  await shot("05-new-exam");
  await page.getByRole("button", { name: /^start$/i }).click();
  await page.waitForURL(/\/exams\/.*\/making/);
  await shot("06-making");
  await page.waitForURL(/\/attempts\/[^/]+$/, { timeout: 240_000 });

  step("flashcards");
  await page.locator(".card .qprompt").waitFor();
  await shot("07-card");
  let shotsTaken = 0;
  for (let i = 1; i <= 5; i++) {
    await page.locator(".card .qprompt").waitFor();
    const type = (await page.locator(".card .qtype").textContent()).trim();
    if (/multiple/i.test(type)) await page.locator(".choice").first().click();
    else if (/true/i.test(type)) await page.locator(".tfb").first().click();
    else { await page.getByLabel("Your answer").fill("Photosynthesis"); await page.getByRole("button", { name: /check/i }).click(); }
    await page.locator(".fb .verdict").waitFor();
    const verdict = (await page.locator(".fb .verdict").textContent()).trim();
    const why = (await page.locator(".fb > p").first().textContent()).trim();
    console.log(`   card ${i} [${type}] -> ${verdict} | ${why.slice(0, 70)}`);
    if (shotsTaken < 2) { await shot(`08-feedback-${++shotsTaken}`); }
    // cannot answer twice
    if (/multiple/i.test(type)) {
      const disabled = await page.locator(".choice").first().isDisabled();
      if (!disabled) throw new Error("choices still enabled after answering");
    }
    const nextBtn = page.locator(".fc-actions .btn.primary");
    const label = (await nextBtn.textContent()).trim();
    if (i < 5 && !/next/i.test(label)) throw new Error(`expected Next, got ${label}`);
    if (i === 5 && !/results/i.test(label)) throw new Error(`expected Results, got ${label}`);
    await nextBtn.click();
  }
  await page.waitForURL(/\/summary$/);

  step("results");
  await page.locator(".score").waitFor();
  const score = (await page.locator(".score").textContent()).replace(/\s+/g, "");
  console.log("   score", score);
  await shot("09-results");
  const retry = page.getByRole("button", { name: /retry/i });
  if (!(await retry.isDisabled())) {
    await retry.click();
    await page.waitForURL(/\/attempts\/[^/]+$/);
    await page.locator(".cardbar .hl", { hasText: "Mistakes" }).waitFor();
    await shot("10-retry-mistakes");
    step("exit sheet -> save & exit");
    await page.getByRole("button", { name: /exit exam/i }).click();
    await page.getByRole("button", { name: /save/i }).click();
    await page.waitForURL(/\/reviewers\//);
  }

  step("exam list shows the score; export");
  await page.locator(".r-exam .score-pill").first().waitFor();
  console.log("   exam row score:", (await page.locator(".r-exam .score-pill").first().textContent()).trim());
  await page.getByRole("button", { name: /export/i }).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: /study sheet/i }).click(),
  ]);
  console.log("   download:", download.suggestedFilename());
  if (!download.suggestedFilename().endsWith(".pdf")) throw new Error("export is not a pdf");

  step("menu: rename");
  await page.getByRole("button", { name: /more options/i }).click();
  await page.getByRole("button", { name: /rename/i }).click();
  await page.getByLabel("Reviewer name").fill("Biology Midterm 2");
  await page.getByRole("button", { name: /save/i }).click();
  await page.getByRole("heading", { name: "Biology Midterm 2" }).waitFor();

  step("home lists it");
  await page.getByRole("link", { name: /back to reviewers/i }).click();
  await page.getByText("Biology Midterm 2").waitFor();
  await shot("11-home");

  const realErrors = consoleErrors.filter((e) => !/favicon/.test(e));
  if (realErrors.length) { console.log("CONSOLE ERRORS:\n" + realErrors.join("\n")); process.exitCode = 1; }
  else console.log("OK — no console errors");
} catch (e) {
  console.error("FAILED:", e.message);
  await page.screenshot({ path: `${SHOTS}/zz-failure.png`, fullPage: true });
  if (consoleErrors.length) console.log("console:", consoleErrors.join("\n"));
  process.exitCode = 1;
} finally {
  await browser.close();
}
