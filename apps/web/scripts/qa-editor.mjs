/**
 * Milestone 5.2 QA: responsive visual checks + full editing workflow for both
 * blur and background replacement, including verified downloads.
 *
 * Dev-only tool (playwright-core, --no-save). Drives the system Chrome.
 * Usage: node apps/web/scripts/qa-editor.mjs <outDir>
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const CLIP = "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\studio-clip.mp4";
const outDir = process.argv[2] ?? join(process.env.TEMP ?? ".", "clipforge-qa");
mkdirSync(outDir, { recursive: true });

const viewports = [
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x800", width: 1280, height: 800 },
  { name: "1024x768", width: 1024, height: 768 },
  { name: "mobile-390x844", width: 390, height: 844 },
];

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const report = { viewports: [], flows: [], console: [] };

function collect(page, tag) {
  page.on("console", (m) => { if (m.type() === "error") report.console.push({ tag, text: m.text() }); });
  page.on("pageerror", (e) => report.console.push({ tag, text: "pageerror: " + e.message }));
}

async function layoutFacts(page) {
  return page.evaluate(() => {
    const box = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
    };
    const tl = document.querySelector('section[aria-label="Timeline"]')?.getBoundingClientRect();
    const transport = document.querySelector('section[aria-label="Viewer"] > div:last-child');
    const clipped = transport ? Array.from(transport.querySelectorAll("button")).some((b) => {
      const r = b.getBoundingClientRect();
      return r.right > innerWidth + 1 || r.left < -1;
    }) : null;
    return {
      viewport: [innerWidth, innerHeight],
      docHeight: document.documentElement.scrollHeight,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
      media: box('section[aria-label="Media"]'),
      viewer: box('section[aria-label="Viewer"]'),
      assistant: box('section[aria-label="AI editing assistant"]'),
      timeline: tl ? { top: Math.round(tl.top), bottom: Math.round(tl.bottom), h: Math.round(tl.height), insideViewport: tl.top >= 0 && tl.bottom <= innerHeight + 1 } : null,
      transportButtonsClipped: clipped,
    };
  });
}

async function runFlow(page, { instruction, label, screenshotBase, expectBackground }) {
  const observedStages = new Set();
  page.on("response", async (res) => {
    if (res.url().match(/\/api\/jobs\/[a-f0-9]+\?*$/) && res.request().method() === "GET") {
      try {
        const body = await res.json();
        if (body?.stage) observedStages.add(body.stage);
      } catch { /* ignored */ }
    }
  });

  await page.setInputFiles('input[type="file"]', CLIP);
  await page.waitForSelector("text=SOURCE — selected", { timeout: 15_000 });

  await page.locator("#typed-instruction").fill(instruction);
  await page.getByRole("button", { name: "Use", exact: true }).click();
  await page.getByRole("button", { name: /Send to ClipForge/ }).click();
  await page.waitForSelector("text=Status: Done", { timeout: 90_000 });
  await page.waitForTimeout(800);

  const facts = await page.evaluate(() => ({
    transcript: (document.body.innerText.match(/PLANNED FROM [A-Z ]*TRANSCRIPT\s*\n([^\n]+)/) || [])[1] ?? null,
    plan: (document.body.innerText.match(/plan: [^\n]+/) || [])[0] ?? null,
    render: (document.body.innerText.match(/render: [^\n]+/) || [])[0] ?? null,
    thumbnails: document.querySelectorAll('section[aria-label="Timeline"] img').length,
    exportEnabled: !Array.from(document.querySelectorAll("header button")).find((b) => /Export MP4/.test(b.textContent))?.disabled,
  }));

  const downloadPromise = page.waitForEvent("download", { timeout: 30_000 });
  await page.getByRole("button", { name: /Export MP4/ }).click();
  const download = await downloadPromise;
  const savedAs = join(outDir, screenshotBase + ".mp4");
  await download.saveAs(savedAs);

  await page.screenshot({ path: join(outDir, screenshotBase + ".png") });
  return { label, observedStages: [...observedStages], facts, savedAs, expectBackground };
}

// Pass 1: responsive layout facts + screenshots (empty and after one completed edit).
for (const vp of viewports) {
  const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
  collect(page, vp.name);
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  const empty = await layoutFacts(page);
  await page.screenshot({ path: join(outDir, `${vp.name}-empty.png`) });

  await page.close();

  const page2 = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
  collect(page2, vp.name + "-flow");
  await page2.goto("http://localhost:3000", { waitUntil: "networkidle" });
  const flow = await runFlow(page2, {
    instruction: "blur the background",
    label: "blur",
    screenshotBase: `${vp.name}-blur-result`,
    expectBackground: false,
  });
  const filled = await layoutFacts(page2);
  report.viewports.push({ viewport: vp.name, empty, filled, flow });
  await page2.close();
}

// Pass 2: background replacement flow at desktop.
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, "replace-1440");
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  const flow = await runFlow(page, {
    instruction: "replace the background with a studio",
    label: "replace",
    screenshotBase: "1440x900-replace-result",
    expectBackground: true,
  });
  report.flows.push(flow);
  await page.close();
}

await browser.close();
console.log(JSON.stringify(report, null, 2));
