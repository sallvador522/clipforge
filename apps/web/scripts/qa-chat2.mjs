/* Chat upgrade QA: interview chips -> idea, chat attach, captions, bg proposal.
 * Mock stack only (API :8003 + web :3003); zero paid calls. Fails on console errors. */
import { execSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const API = "http://127.0.0.1:8003";
const WEB = "http://127.0.0.1:3003";
const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
let execCount = 0;
page.on("request", (req) => { if (req.url().includes("/tools/execute")) execCount += 1; });
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

async function proxy(route) {
  const url = new URL(route.request().url());
  const target = `${API}${url.pathname}${url.search}`;
  const headers = {};
  const ct = route.request().headers()["content-type"];
  if (ct) headers["content-type"] = ct;
  const init = { method: route.request().method(), headers };
  let post = route.request().postDataBuffer();
  // Playwright truncates streamed XHR file bodies: rebuild the clip upload
  // from the file on disk (same field name, same boundary).
  if (url.pathname === "/api/uploads" && process.env.CLIP_PATH) {
    const boundary = (ct.match(/boundary=(.+)$/) || [])[1];
    const fileBytes = readFileSync(process.env.CLIP_PATH);
    const head = Buffer.from(
      `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="clip.mp4"\r\nContent-Type: video/mp4\r\n\r\n`);
    const tail = Buffer.from(`\r\n--${boundary}--\r\n`);
    post = Buffer.concat([head, fileBytes, tail]);
  }
  if (post) init.body = post;
  try {
    const res = await fetch(target, init);
    const buf = Buffer.from(await res.arrayBuffer());
    await route.fulfill({ status: res.status, headers: { "content-type": res.headers.get("content-type") ?? "application/json" }, body: buf });
  } catch (e) {
    await route.abort();
  }
}
await page.route("http://localhost:8000/**", proxy);
await page.route("http://127.0.0.1:8000/**", proxy);

function api(path, opts = {}) {
  return fetch(`${API}${path}`, {
    ...opts,
    headers: { "content-type": "application/json", ...(opts.headers ?? {}) },
  });
}

const tmp = mkdtempSync(join(tmpdir(), "qa-chat2-"));
const clip = join(tmp, "clip.mp4");
execSync(`ffmpeg -y -f lavfi -i color=c=green:size=320x180:rate=30:duration=4 -f lavfi -i sine=frequency=440:duration=4 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "${clip}"`, { stdio: "ignore" });

await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.evaluate(() => { window.localStorage.clear(); });
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.getByLabel("Mensagem para o Muse").waitFor({ timeout: 30000 });

// 1. Interview: empty platform -> style question with chips.
await page.getByLabel("Mensagem para o Muse").fill("quero um video sobre o mar");
await page.getByLabel("Mensagem para o Muse").press("Enter");
await page.getByRole("group", { name: "Que estilo queres para o vídeo?" }).waitFor({ timeout: 15000 });
console.log("interview style question OK");
await page.getByRole("button", { name: "Documental" }).click();
await page.getByRole("group", { name: "Qual a duração?" }).waitFor({ timeout: 15000 });
console.log("interview duration question OK");
await page.getByRole("group", { name: "Qual a duração?" }).getByRole("button", { name: "30s" }).click();
await page.getByRole("group", { name: "Formato vertical" }).waitFor({ timeout: 15000 });
console.log("interview aspect question OK");
await page.getByRole("button", { name: "Vertical 9:16" }).click();
await page.getByText("Posso executar?").waitFor({ timeout: 15000 });
const cardText = await page.locator("p.font-mono").first().textContent();
if (!cardText || !cardText.includes("documentary") || !cardText.includes("30")) throw new Error("options summary missing: " + cardText);
console.log("interview proposal with options OK:", cardText.trim());
await page.getByRole("button", { name: "Executar" }).click();
await page.waitForFunction(() => window.localStorage.getItem("clipforge.idea.last"), null, { timeout: 20000 });
const ideaId = await page.evaluate(() => window.localStorage.getItem("clipforge.idea.last"));
if (!ideaId) throw new Error("idea was not created after Executar");
const idea = await (await api(`/api/ideas/${ideaId}`)).json();
if (idea.options.style_preset !== "documentary" || idea.options.duration_seconds !== 30 || idea.options.aspect_ratio !== "9:16") {
  throw new Error("idea options mismatch: " + JSON.stringify(idea.options));
}
console.log("idea created with interview options OK:", ideaId);

// 2. Attach a video from the chat.
await page.evaluate(() => { window.localStorage.clear(); });
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.getByLabel("Mensagem para o Muse").waitFor({ timeout: 30000 });
await page.locator('input[aria-label="Anexar vídeo ao chat"]').setInputFiles(clip);
await page.getByText(/pronto\. Descreve a altera/).waitFor({ timeout: 30000 });
console.log("chat attach OK (real upload path)");
const jobId = await page.evaluate(() => window.localStorage.getItem("clipforge.jobId"));
if (!jobId) throw new Error("attach did not store a job id");
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.getByLabel("Mensagem para o Muse").waitFor({ timeout: 30000 });

// 3. Captions through Muse: propose -> Executar -> persisted overlays.
await page.getByRole("tab", { name: "Muse" }).click();
await page.getByLabel("Mensagem para o Muse").fill("adiciona legendas 'Ola mundo do chat'");
await page.getByLabel("Mensagem para o Muse").press("Enter");
await page.getByText("Posso executar?").waitFor({ timeout: 15000 });
const toolLine = await page.locator("li.font-mono").first().textContent();
if (!toolLine || !toolLine.includes("captions.create")) throw new Error("no captions tool call: " + toolLine);
const execBeforeCaptions = execCount;
await page.getByRole("button", { name: "Executar" }).click();
// NB: chat bubbles animate opacity 0->1; headless Chromium may never run
// the frames, so assert on textContent (message pushed with right content).
await page.waitForFunction(() => (document.body.textContent || "").includes("legendas: 1 linha"), null, { timeout: 25000 });
if (execCount !== execBeforeCaptions + 1) throw new Error("captions executed more than once");
const texts = (await (await api(`/api/jobs/${jobId}/texts`)).json()).texts;
if (texts.length !== 1 || texts[0].text !== "Ola mundo do chat") throw new Error("captions not persisted: " + JSON.stringify(texts));
console.log("captions tool execution OK");

// 4. Background removal proposal names the Meta path.
await page.getByRole("tab", { name: "Muse" }).click();
await page.getByLabel("Mensagem para o Muse").fill("remove o fundo");
await page.getByLabel("Mensagem para o Muse").press("Enter");
await page.getByText(/SAM 3\.1/).waitFor({ timeout: 15000 });
console.log("bg proposal names SAM path OK");
await page.getByRole("button", { name: "Cancelar" }).click();

// 4b. Translation proposal names the price, no execution (would bill).
await page.getByRole("tab", { name: "Muse" }).click();
await page.getByLabel("Mensagem para o Muse").fill("traduz para português 'Hello world'");
await page.getByLabel("Mensagem para o Muse").press("Enter");
await page.getByText("Posso executar?").waitFor({ timeout: 15000 });
const trLine = await page.locator("li.font-mono").first().textContent();
if (!trLine || !trLine.includes("captions.translate")) throw new Error("no translate tool call: " + trLine);
await page.getByText(/\$0\.0001/).first().waitFor({ timeout: 15000 });
console.log("translate proposal names price OK (not executed)");
await page.getByRole("button", { name: "Cancelar" }).click();

// 5. Burned-in cover: propose -> Executar -> flag persisted.
await page.getByRole("tab", { name: "Muse" }).click();
await page.getByLabel("Mensagem para o Muse").fill("tapa as legendas queimadas");
await page.getByLabel("Mensagem para o Muse").press("Enter");
await page.getByText(/Tapo a faixa/).first().waitFor({ timeout: 15000 });
await page.getByText("Posso executar?").waitFor({ timeout: 15000 });
const coverLine = await page.locator("li.font-mono").first().textContent();
if (!coverLine || !coverLine.includes("captions.cover")) throw new Error("no cover tool call: " + coverLine);
const execBeforeCover = execCount;
await page.getByRole("button", { name: "Executar" }).click();
await page.waitForFunction(() => (document.body.textContent || "").includes("cobertura da faixa: ligada"), null, { timeout: 25000 });
const cover = await (await api(`/api/jobs/${jobId}/caption-cover`)).json();
if (cover.caption_cover !== true) throw new Error("cover not persisted: " + JSON.stringify(cover));
console.log("cover tool execution OK");

if (execCount !== execBeforeCover + 1) throw new Error("cover executed more than once");
await browser.close();
if (errors.length > 0) {
  console.error("CONSOLE ERRORS:", errors);
  process.exit(1);
}
console.log("CHAT2-QA PASS: zero console errors");
