/* Magic Background browser QA (ADR-052): chat -> director plan -> review ->
 * subject select -> approve -> real worker render -> verified download.
 * Mock stack only (API :8004 + worker + web :3004); zero paid calls. */
import { execSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const API = "http://127.0.0.1:8004";
const WEB = "http://127.0.0.1:3004";
const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

async function proxy(route) {
  const url = new URL(route.request().url());
  const target = `${API}${url.pathname}${url.search}`;
  const headers = {};
  const ct = route.request().headers()["content-type"];
  if (ct) headers["content-type"] = ct;
  const init = { method: route.request().method(), headers };
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

const tmp = mkdtempSync(join(tmpdir(), "qa-magicbg-"));
const clip = join(tmp, "clip.mp4");
execSync(`ffmpeg -y -f lavfi -i testsrc=size=320x180:rate=30:duration=4 -f lavfi -i sine=frequency=440:duration=4 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "${clip}"`, { stdio: "ignore" });

await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.evaluate(() => { window.localStorage.clear(); });
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.getByLabel("Mensagem para o Muse").waitFor({ timeout: 30000 });

// 1. Upload via chat attach, then ask for the animated blue background.
const fileInput = page.locator('input[aria-label="Anexar vídeo ao chat"]');
// Multipart bodies are truncated by interception; upload via API, announce via chat.
{
  const form = new FormData();
  form.append("file", new Blob([readFileSync(clip)], { type: "video/mp4" }), "clip.mp4");
  const upRes = await fetch(`${API}/api/uploads`, { method: "POST", body: form });
  if (!upRes.ok) throw new Error("upload failed: " + upRes.status);
  const jobId = (await upRes.json()).job_id;
  console.log("uploaded job", jobId);
  await page.evaluate((id) => { window.localStorage.setItem("clipforge.jobId", id); }, jobId);
}
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.getByLabel("Mensagem para o Muse").waitFor({ timeout: 30000 });
await page.getByRole("tab", { name: "Muse" }).click();
await page.getByLabel("Mensagem para o Muse").fill("substitui o fundo por um gradiente azul animado minimalista");
await page.getByLabel("Mensagem para o Muse").press("Enter");
await page.getByText("Posso executar?").waitFor({ timeout: 15000 });
console.log("chat proposal (director flow) OK");
await page.getByRole("button", { name: "Executar" }).click();

// 2. Plan review dialog opens (auto-open): select a detected subject, approve.
await page.getByText("Pessoas detectadas").waitFor({ timeout: 60000 });
console.log("plan review with subject selection OK");
await page.getByRole("button", { name: /Pessoa / }).first().click();
await page.getByRole("button", { name: "Aprovar selecção e gerar" }).click();
console.log("subject selected, render approved");

// 3. Wait for verified completion, then download the real MP4.
await page.waitForFunction(
  () => document.body.textContent.includes("Vídeo pronto e verificado"),
  null, { timeout: 240000 });
console.log("render completed + verified OK");
const downloadPromise = page.waitForEvent("download");
await page.getByRole("button", { name: "Exportar" }).click();
const download = await downloadPromise;
const outPath = join(tmp, "magicbg.mp4");
await download.saveAs(outPath);
const { size } = await import("node:fs").then((fs) => fs.promises.stat(outPath));
if (size < 10000) throw new Error("download too small: " + size);
console.log("downloaded verified MP4 bytes:", size);

await browser.close();
if (errors.length > 0) {
  console.error("CONSOLE ERRORS:", errors);
  process.exit(1);
}
console.log("MAGICBG-QA PASS: zero console errors");
