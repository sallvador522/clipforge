/**
 * Milestone 5.2 real-footage check: edit a 10 s excerpt of the user's
 * C:\Users\New User\Videos\Video\Facebook_2.mp4 (360x640 portrait, 25 fps).
 * The original stays untouched; the excerpt exists only because the MVP input
 * contract is ≤10 s. Mock segmentation means the mask is a synthetic ellipse,
 * NOT a tracked person — screenshots must be read with that in mind.
 *
 * Usage: node apps/web/scripts/qa-facebook.mjs <outDir>
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const CLIP = "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\Facebook_2_10s.mp4";
const outDir = process.argv[2] ?? join(process.env.TEMP ?? ".", "clipforge-facebook");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ executablePath: CHROME, headless: true });

async function run(label, fixture, fileBase) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  await page.setInputFiles('input[type="file"]', CLIP);
  await page.waitForSelector("text=SOURCE — selected", { timeout: 15_000 });
  await page.waitForTimeout(600);
  await page.screenshot({ path: join(outDir, `${fileBase}-source.png`) });

  await page.getByRole("button", { name: "Upload & create job" }).click();
  await page.waitForSelector("text=Uploaded — job created", { timeout: 30_000 });
  await page.getByRole("radio", { name: fixture }).click();
  await page.getByRole("button", { name: "Start voice recording" }).click();
  await page.getByRole("button", { name: /Continue without a microphone/ }).click({ timeout: 10_000 });
  await page.getByRole("button", { name: /Confirm & start editing/ }).click();

  await page.waitForSelector("text=Status: completed", { timeout: 240_000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: join(outDir, `${fileBase}-result.png`) });

  const facts = await page.evaluate(() => ({
    transcript: (document.body.innerText.match(/TRANSCRIPTION \(MOCK\)\s*\n([^\n]+)/) || [])[1] ?? null,
    plan: (document.body.innerText.match(/plan: [^\n]+/) || [])[0] ?? null,
    render: (document.body.innerText.match(/render: [^\n]+/) || [])[0] ?? null,
    job: (document.body.innerText.match(/job [a-f0-9]{6,}/) || [])[0] ?? null,
  }));

  const dl = page.waitForEvent("download", { timeout: 60_000 });
  await page.getByRole("button", { name: /Export MP4/ }).click();
  const download = await dl;
  const saved = join(outDir, `${fileBase}.mp4`);
  await download.saveAs(saved);
  await page.close();
  return { label, facts, saved, consoleErrors: errors };
}

const blur = await run("blur", /Blur the background/, "facebook-blur");
const replace = await run("replace", /Replace with a studio/, "facebook-replace");
await browser.close();
console.log(JSON.stringify({ blur, replace }, null, 2));
