/* ADR-047 rescue QA: real browser proof of selection -> properties ->
 * persistence -> Muse tools -> Montar -> verified. Mock stack only
 * (API :8001 + web :3001); zero paid calls. Fails on console errors. */
import { execSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const API = "http://127.0.0.1:8001";
const WEB = "http://127.0.0.1:3001";
const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

// Isolate from any other stack on :8000: proxy every API call to :8001.
async function proxy(route) {
  const url = new URL(route.request().url());
  const target = `${API}${url.pathname}${url.search}`;
  const init = { method: route.request().method(), headers: { "content-type": "application/json" } };
  const post = route.request().postDataBuffer();
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

const tmp = mkdtempSync(join(tmpdir(), "qa-rescue-"));
const clip = join(tmp, "clip.mp4");
execSync(`ffmpeg -y -f lavfi -i color=c=blue:size=320x180:rate=30:duration=4 -f lavfi -i sine=frequency=440:duration=4 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "${clip}"`, { stdio: "ignore" });

const form = new FormData();
form.append("file", new Blob([readFileSync(clip)], { type: "video/mp4" }), "clip.mp4");
const upRes = await fetch(`${API}/api/uploads`, { method: "POST", body: form });
if (!upRes.ok) throw new Error("upload failed: " + upRes.status);
const jobId = (await upRes.json()).job_id;
console.log("job", jobId);

await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.evaluate((id) => {
  window.localStorage.clear();
  window.localStorage.setItem("clipforge.jobId", id);
}, jobId);
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.getByLabel("Mensagem para o Muse").waitFor({ timeout: 30000 });

// 1. Add text via the Texto tab.
await page.getByRole("button", { name: "Texto" }).first().click();
await page.getByRole("button", { name: /Adicionar texto Fundido a subir/ }).click();
await page.waitForTimeout(800);
let texts = (await (await api(`/api/jobs/${jobId}/texts`)).json()).texts;
if (texts.length !== 1) throw new Error("expected 1 persisted overlay, got " + texts.length);
console.log("persisted after add:", texts[0].overlay_id);

// 2. Adding selects the overlay -> Properties shows it (same-tab reveal).
await page.getByText("Texto selecionado").waitFor({ timeout: 10000 });
console.log("selection -> properties OK");
// Deselect by clicking the overlay again, then re-select via the preview.
await page.getByRole("button", { name: /arrasta para posicionar/ }).first().click();
await page.getByText("Texto selecionado").waitFor({ state: "detached", timeout: 10000 });
await page.getByRole("button", { name: /arrasta para posicionar/ }).first().click();
await page.getByText("Texto selecionado").waitFor({ timeout: 10000 });
console.log("deselect -> reselect OK");

// 3. Edit content in Properties -> backend updated.
await page.getByLabel("Conteúdo do texto").fill("Resgate final");
await page.waitForTimeout(1200);
texts = (await (await api(`/api/jobs/${jobId}/texts`)).json()).texts;
if (texts[0].text !== "Resgate final") throw new Error("properties edit did not persist: " + texts[0].text);
console.log("properties edit persisted OK");

// 4. Inline editing: double-click -> input -> Enter.
await page.getByRole("button", { name: /arrasta para posicionar/ }).first().dblclick();
await page.getByLabel("Editar texto").waitFor({ timeout: 10000 });
await page.getByLabel("Editar texto").fill("Inline funciona");
await page.getByLabel("Editar texto").press("Enter");
await page.waitForTimeout(1200);
texts = (await (await api(`/api/jobs/${jobId}/texts`)).json()).texts;
if (texts[0].text !== "Inline funciona") throw new Error("inline edit did not persist");
console.log("inline edit persisted OK");

// 5. Colour grade via Properties sliders + apply.
await page.getByLabel("Contraste").fill("1.25");
await page.getByRole("button", { name: "Aplicar cor" }).click();
await page.waitForTimeout(800);
const colour = (await (await api(`/api/jobs/${jobId}/colour`)).json()).colour;
if (Math.abs(colour.contrast - 1.25) > 1e-9) throw new Error("colour did not persist: " + JSON.stringify(colour));
console.log("colour grade persisted OK");

// 6. Muse chat proposes a real tool call; Executar runs it.
await page.getByRole("tab", { name: "Muse" }).click();
await page.getByLabel("Mensagem para o Muse").fill("Muda o texto para 'Feito no palco'");
await page.getByLabel("Mensagem para o Muse").press("Enter");
await page.getByText("Posso executar?").waitFor({ timeout: 15000 });
const toolLine = await page.locator("li.font-mono").first().textContent();
if (!toolLine || !toolLine.includes("text.update")) throw new Error("no real tool call shown: " + toolLine);
await page.getByRole("button", { name: "Executar" }).click();
await page.getByText(/Executei:/).waitFor({ timeout: 15000 });
texts = (await (await api(`/api/jobs/${jobId}/texts`)).json()).texts;
if (texts[0].text !== "Feito no palco") throw new Error("Muse tool edit did not apply: " + texts[0].text);
console.log("muse tool execution OK");

// 7. Timeline auto-placed the session clip; Montar -> verified.
await page.getByRole("button", { name: /Montar/ }).first().click();
await page.waitForTimeout(2000);
let state = "";
for (let i = 0; i < 40; i++) {
  const j = await (await api(`/api/jobs/${jobId}`)).json();
  state = `${j.status}/${j.stage}`;
  if (j.status === "completed") break;
  await page.waitForTimeout(3000);
}
if (!state.startsWith("completed")) throw new Error("montar did not complete: " + state);
const result = await (await api(`/api/jobs/${jobId}/result`)).json();
if (result.render_status !== "verified") throw new Error("render not verified");
console.log("montar verified OK:", state);

await browser.close();
if (errors.length > 0) {
  console.error("CONSOLE ERRORS:", errors);
  process.exit(1);
}
console.log("RESCUE-QA PASS: zero console errors");
