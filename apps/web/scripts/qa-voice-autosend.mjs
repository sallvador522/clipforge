import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const outDir = join(process.env.TEMP ?? ".", "clipforge-voice-autosend");
mkdirSync(outDir, { recursive: true });

const report = { transcribePosts: 0, chatPosts: 0, chatBody: null, consoleErrors: [] };

const browser = await chromium.launch({
  executablePath: CHROME,
  headless: true,
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["microphone"] });
const page = await context.newPage();
page.on("console", (m) => { if (m.type() === "error") report.consoleErrors.push(m.text()); });
page.on("pageerror", (e) => report.consoleErrors.push(String(e)));

await page.route("**/health", async (route) => {
  const response = await route.fetch();
  const body = await response.json();
  body.transcribe_mode = "live";
  body.live_transcription_available = true;
  await route.fulfill({ response, json: body });
});
await page.route("**/api/transcribe", async (route) => {
  report.transcribePosts += 1;
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      text: "desfoca o fundo por favor",
      language: "pt-BR",
      confidence: 0.9,
      provider_name: "test-mic",
      is_mock: false,
      session_id: "qa-voice-1",
      audio_duration_ms: 2500,
      transcribe_mode: "live",
    }),
  });
});
await page.route("**/api/chat", async (route) => {
  report.chatPosts += 1;
  try { report.chatBody = route.request().postDataJSON(); } catch { report.chatBody = null; }
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      intent: "clarify",
      reply: "QA Muse: recebi a tua voz.",
      needs_confirmation: false,
      pending_text: null,
      pending_kind: null,
      pending_tool_calls: [],
      chat_mode: "mock",
    }),
  });
});

await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
const mic = page.getByRole("button", { name: "Gravar mensagem de voz" });
await mic.waitFor({ timeout: 15000 });
await mic.click({ force: true });
await page.getByRole("button", { name: "Parar gravação" }).waitFor({ timeout: 10000 });
await page.waitForTimeout(1500);
await page.getByRole("button", { name: "Parar gravação" }).click({ force: true });

await page.waitForFunction(() => document.body.innerText.includes("QA Muse: recebi a tua voz."), { timeout: 20000 });
report.userMessageVisible = await page.evaluate(() => document.body.innerText.includes("desfoca o fundo por favor"));
report.museReplyVisible = true;
report.draftAfter = await page.evaluate(() => {
  const el = document.querySelector('textarea[aria-label="Mensagem para o Muse"]');
  return el ? el.value : null;
});
report.sentToMuseText = await page.evaluate(() => document.body.innerText.includes("Enviado ao Muse."));
await page.screenshot({ path: join(outDir, "voice-autosend.png"), fullPage: false });
console.log(JSON.stringify({ report, outDir }, null, 2));
await browser.close();
if (report.transcribePosts !== 1 || report.chatPosts !== 1 || report.chatBody?.message !== "desfoca o fundo por favor") {
  process.exitCode = 2;
}
