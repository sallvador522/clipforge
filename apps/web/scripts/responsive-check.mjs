/**
 * Responsive QA harness (dev-only, not shipped): drives the system Chrome via
 * playwright-core at the required editor viewports, seeds a source clip into
 * the Media panel, and records layout facts + screenshots.
 *
 * Usage: node scripts/responsive-check.mjs [outputDir]
 */
import { chromium } from "playwright-core";
import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const outDir = process.argv[2] ?? join(process.env.TEMP ?? ".", "clipforge-responsive");
mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x800", width: 1280, height: 800 },
  { name: "1024x768", width: 1024, height: 768 },
  { name: "mobile-390x844", width: 390, height: 844 },
];

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const results = [];

for (const vp of viewports) {
  const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  const facts = await page.evaluate(() => {
    const rect = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
    };
    const tl = document.querySelector('section[aria-label="Timeline"]')?.getBoundingClientRect();
    const viewer = document.querySelector('section[aria-label="Viewer"]')?.getBoundingClientRect();
    return {
      viewport: [innerWidth, innerHeight],
      docScrollHeight: document.documentElement.scrollHeight,
      media: rect('section[aria-label="Media"]'),
      viewer: viewer ? { w: Math.round(viewer.width), h: Math.round(viewer.height) } : null,
      assistant: rect('section[aria-label="AI editing assistant"]'),
      timeline: tl ? { top: Math.round(tl.top), bottom: Math.round(tl.bottom), h: Math.round(tl.height), insideViewport: tl.top >= 0 && tl.bottom <= innerHeight + 1 } : null,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
    };
  });
  await page.screenshot({ path: join(outDir, `${vp.name}-empty.png`) });

  // Seed the real flow: upload the local clip, attach voice, render, verify.
  await page.setInputFiles('input[type="file"]', "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\studio-clip.mp4");
  await page.waitForSelector("text=SOURCE — selected", { timeout: 15_000 });
  await page.getByRole("button", { name: "Upload & create job" }).click();
  await page.waitForSelector("text=Uploaded — job created", { timeout: 30_000 });
  await page.getByRole("radio", { name: /Keep me sharp, blur/ }).click({ timeout: 15_000 });
  // Typed-instruction path: deterministic, microphone-independent, and exercises the accessible alternative.
  await page.locator("#typed-instruction").fill("keep me sharp and blur the rest");
  await page.getByRole("button", { name: "Use", exact: true }).click();
  await page.getByRole("button", { name: /Confirm & start editing/ }).click();
  await page.waitForSelector("text=Status: completed", { timeout: 60_000 });
  await page.waitForTimeout(1200);
  const after = await page.evaluate(() => {
    const rect = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height) };
    };
    return {
      imagesInTimeline: document.querySelectorAll('section[aria-label="Timeline"] img').length,
      exportEnabled: !document.querySelector("header button")?.disabled,
      status: (document.body.innerText.match(/Status:\s*\w+/) || [])[0],
      viewer: rect('section[aria-label="Viewer"]'),
    };
  });
  await page.screenshot({ path: join(outDir, `${vp.name}-result.png`) });
  results.push({ viewport: vp.name, facts, after });
  await page.close();
}

await browser.close();
console.log(JSON.stringify({ outDir, results }, null, 2));
