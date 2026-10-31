import { chromium } from "playwright-core";
const browser = await chromium.launch({ executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const external = [];
page.on("request", (r) => { if (r.url().includes("api.meta.ai")) external.push(r.url()); });
await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
const facts = await page.evaluate(() => ({
  badge: (document.body.innerText.match(/LIVE TRANSCRIPTION|MOCK TRANSCRIPTION/) || [])[0],
  fixturesVisible: document.querySelectorAll('[role="radiogroup"][aria-label="Simulated voice command"] [role="radio"]').length,
  mockNote: document.body.innerText.includes("MOCK TRANSCRIPTION — simulated"),
  transcribeButtonBeforeRecording: Array.from(document.querySelectorAll("button")).some((b) => /Transcribe recording/.test(b.textContent)),
  healthTopBar: (document.body.innerText.match(/ASR (live|mock)/) || [])[0],
}));
await page.screenshot({ path: "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\live-ui.png" });
await browser.close();
console.log(JSON.stringify({ facts, external, note: "No recording was made and no transcribe request was sent." }, null, 2));
