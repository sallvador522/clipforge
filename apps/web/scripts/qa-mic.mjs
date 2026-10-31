/**
 * Milestone 5.2 microphone QA — real device, no fake audio.
 *
 * Launches system Chrome (headed) with only the permission PROMPT auto-accepted;
 * getUserMedia still uses the machine's actual default input device. Records 3 s,
 * samples the UI's real analyser-driven level bar, stops, verifies the recorded
 * blob duration and playback, and captures screenshots. If Chrome reports no
 * device or a denial, that result is reported as-is.
 *
 * Usage: node apps/web/scripts/qa-mic.mjs <outDir>
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const outDir = process.argv[2] ?? join(process.env.TEMP ?? ".", "clipforge-mic");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({
  executablePath: CHROME,
  headless: false, // real window: headless Chrome here has no audio input device
  args: ["--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
});
const context = await browser.newContext({ permissions: ["microphone"], viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
await page.setInputFiles('input[type="file"]', "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\studio-clip.mp4");
await page.waitForSelector("text=SOURCE — selected");

const result = { device: "system default input (real)", steps: [] };
await page.getByRole("button", { name: "Start voice recording" }).click();

let state = "unknown";
try {
  await page.waitForSelector("text=Listening…", { timeout: 8_000 });
  state = "recording";
} catch {
  const body = await page.evaluate(() => document.body.innerText);
  state = /permission denied/i.test(body) ? "denied" : /unavailable/i.test(body) ? "unsupported" : "no-response";
}
result.steps.push({ step: "start_recording", state });

if (state === "recording") {
  await page.screenshot({ path: join(outDir, "microphone-recording.png") });
  const samples = [];
  for (let i = 0; i < 20; i++) {
    const s = await page.evaluate(() => {
      const bar = document.querySelector('section[aria-label="AI editing assistant"] div[aria-hidden="true"] > div');
      const timer = document.body.innerText.match(/00:\d\d/);
      return { width: bar ? bar.style.width : null, timer: timer ? timer[0] : null };
    });
    samples.push(s);
    await page.waitForTimeout(150);
  }
  const numeric = samples.map((s) => (s.width ? parseInt(s.width, 10) : 0));
  result.steps.push({
    step: "live_level_samples",
    max_percent: Math.max(...numeric),
    samples: numeric,
    timers: [...new Set(samples.map((s) => s.timer).filter(Boolean))],
  });

  await page.waitForTimeout(1200);
  await page.getByRole("button", { name: "Stop recording" }).click();
  await page.waitForSelector("text=Recorded 00:", { timeout: 8_000 });
  const recordedText = await page.evaluate(() => (document.body.innerText.match(/Recorded 00:\d\d/) || [])[0]);
  const audio = await page.evaluate(async () => {
    const el = document.querySelector('section[aria-label="AI editing assistant"] audio');
    if (!el) return null;
    if (el.readyState < 1) await new Promise((r) => el.addEventListener("loadedmetadata", r, { once: true }));
    return { duration: el.duration, srcIsBlob: el.src.startsWith("blob:") };
  });
  result.steps.push({ step: "stopped", recordedText, audio });

  const playback = await page.evaluate(async () => {
    const el = document.querySelector('section[aria-label="AI editing assistant"] audio');
    if (!el) return null;
    await el.play();
    await new Promise((r) => setTimeout(r, 700));
    const t = el.currentTime;
    el.pause();
    return { advancedTo: t, paused: el.paused };
  });
  result.steps.push({ step: "playback", playback });
  await page.screenshot({ path: join(outDir, "microphone-recorded.png") });
}

result.consoleErrors = consoleErrors;
await browser.close();
console.log(JSON.stringify(result, null, 2));
