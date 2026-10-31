/**
 * Milestone 5.2 interaction QA: transport, playback/playhead sync, view modes,
 * compare split, export gating, request polling behaviour, and the
 * permission-denied microphone state (headless has no mic permission).
 *
 * Usage: node apps/web/scripts/qa-interactions.mjs <outDir>
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const CLIP = "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\studio-clip.mp4";
const outDir = process.argv[2] ?? join(process.env.TEMP ?? ".", "clipforge-interactions");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
await page.goto("http://localhost:3000", { waitUntil: "networkidle" });

const report = {};

// Export must be disabled until a verified render exists.
report.exportDisabledBeforeResult = await page.evaluate(() =>
  Array.from(document.querySelectorAll("header button")).find((b) => /Export MP4/.test(b.textContent))?.disabled);

await page.setInputFiles('input[type="file"]', CLIP);
await page.waitForSelector("text=SOURCE — selected");

// Permission-denied path (headless context has no microphone grant).
await page.getByRole("button", { name: "Start voice recording" }).click();
await page.waitForSelector("text=Microphone permission denied", { timeout: 10_000 });
report.deniedStateShown = true;
report.mockTranscriptAlternativeVisible = await page
  .getByRole("button", { name: /Use selected command as transcript/ })
  .isVisible();
await page.screenshot({ path: join(outDir, "mic-permission-denied.png") });

// Playback + playhead sync before any job exists.
await page.getByRole("button", { name: "Play", exact: true }).click();
await page.waitForTimeout(900);
report.playback = await page.evaluate(() => {
  const v = document.querySelector('section[aria-label="Viewer"] video');
  const playhead = document.querySelector('section[aria-label="Timeline"] div[style*="left"]');
  const rect = playhead?.getBoundingClientRect();
  const track = document.querySelector('section[aria-label="Timeline"] div[role="slider"]')?.getBoundingClientRect();
  return {
    currentTime: v?.currentTime,
    paused: v?.paused,
    playheadPct: rect && track ? Math.round(((rect.left - track.left) / track.width) * 100) : null,
  };
});
await page.getByRole("button", { name: "Pause", exact: true }).click();
report.paused = await page.evaluate(() => document.querySelector('section[aria-label="Viewer"] video')?.paused);

// Seek via the timeline ruler to ~75%.
await page.evaluate(() => {
  const track = document.querySelector('section[aria-label="Timeline"] div[role="slider"]');
  const r = track.getBoundingClientRect();
  track.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, clientX: r.left + r.width * 0.75 }));
});
await page.waitForTimeout(200);
report.seek = await page.evaluate(() => ({
  currentTime: document.querySelector('section[aria-label="Viewer"] video')?.currentTime,
  displayed: (document.body.innerText.match(/00:0\d\.\d/) || [])[0],
}));

// Full editing run (blur), then verify view modes and polling stop.
const pollRequests = [];
page.on("request", (r) => {
  if (r.url().match(/\/api\/jobs\/[a-f0-9]+$/) && r.method() === "GET") pollRequests.push(Date.now());
});

await page.getByRole("button", { name: "Upload & create job" }).click();
await page.waitForSelector("text=Uploaded — job created", { timeout: 30_000 });
await page.getByRole("radio", { name: /Blur the background/ }).click();
await page.getByRole("button", { name: /Use selected command as transcript/ }).click();
await page.getByRole("button", { name: /Confirm transcript & start editing/ }).click();
await page.waitForSelector("text=Status: completed", { timeout: 90_000 });
const requestsAtCompletion = pollRequests.length;
await page.waitForTimeout(5000);
report.polling = { atCompletion: requestsAtCompletion, after5s: pollRequests.length, stopped: pollRequests.length === requestsAtCompletion };

report.exportEnabledAfterResult = await page.evaluate(() =>
  !Array.from(document.querySelectorAll("header button")).find((b) => /Export MP4/.test(b.textContent))?.disabled);

report.modes = {};
for (const mode of ["Before", "After", "Compare"]) {
  await page.getByRole("tab", { name: mode }).click();
  await page.waitForTimeout(300);
  report.modes[mode] = await page.evaluate((m) => {
    const stage = document.querySelector('section[aria-label="Viewer"]');
    const vids = Array.from(stage.querySelectorAll("video")).map((v) => ({
      src: v.getAttribute("src") ?? "",
      visible: getComputedStyle(v).visibility !== "hidden",
      clip: v.style.clipPath || null,
    }));
    return { selected: Array.from(stage.querySelectorAll('[role="tab"]')).find((t) => t.getAttribute("aria-selected") === "true")?.textContent, videos: vids.length, note: m === "After" ? vids.some((v) => v.src.includes("/download")) : true };
  }, mode);
}

// Compare split changes clip-path.
await page.getByRole("tab", { name: "Compare" }).click();
const split = page.getByRole("slider", { name: "Compare split position" });
await split.fill("30");
report.splitClipPath = await page.evaluate(() => {
  const el = document.querySelector('section[aria-label="Viewer"] [style*="clip-path"]');
  return el?.style.clipPath ?? null;
});

await page.screenshot({ path: join(outDir, "interactions-result.png") });
report.consoleErrors = errors;
await browser.close();
console.log(JSON.stringify(report, null, 2));
