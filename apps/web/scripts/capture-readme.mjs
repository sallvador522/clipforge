/**
 * Capture a README screenshot of the editor with a real clip loaded.
 * Does not confirm a voice instruction, so no AI/render job is executed.
 *
 * Usage (from apps/web):
 *   node scripts/capture-readme.mjs ../../docs/assets/clipforge-editor.png
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";

const CHROME = process.env.CHROME_PATH ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const CLIP =
  process.env.CLIPFORGE_CLIP ??
  "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\studio-clip.mp4";
const out = resolve(process.argv[2] ?? "../../docs/assets/clipforge-editor.png");
mkdirSync(dirname(out), { recursive: true });

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
});

const errors = [];
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));

await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
await page.setInputFiles('input[type="file"]', CLIP);
await page.waitForSelector("text=JOB PROGRESS", { timeout: 15_000 });
await page.fill("#typed-instruction", "Blur the background");
await page.locator("#typed-instruction").press("Home");
await page.waitForTimeout(400);
await page.screenshot({ path: out });

console.log(JSON.stringify({ out, errors }, null, 2));
await browser.close();
