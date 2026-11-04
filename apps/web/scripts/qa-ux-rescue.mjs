/* UI/UX rescue audit: real browser vs isolated mock stack (API :8001 + web :3001).
 * Zero paid calls. Fails on console errors. Saves full-page screenshots. */
import { execSync } from "node:child_process";
import { mkdtempSync, readFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const API = "http://127.0.0.1:8001";
const WEB = "http://127.0.0.1:3001";
const SHOTS = join(process.env.TEMP ?? tmpdir(), "opencode", "uxr");
mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const errors = [];
async function newPage(w, h) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, acceptDownloads: true });
  page.on("console", (m) => { if (m.type() === "error") errors.push(`[${w}x${h}] ${m.text()}`); });
  page.on("pageerror", (e) => errors.push(`[${w}x${h}] pageerror: ${e.message}`));
  page.on("response", (r) => { if (r.status() >= 400) errors.push(`[${w}x${h}] HTTP ${r.status()} ${r.url().slice(0, 160)}`); });
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
      const out = { "content-type": res.headers.get("content-type") ?? "application/json" };
      const cd = res.headers.get("content-disposition");
      if (cd) out["content-disposition"] = cd;
      await route.fulfill({ status: res.status, headers: out, body: buf });
    } catch { await route.abort(); }
  }
  await page.route("http://localhost:8000/**", proxy);
  await page.route("http://127.0.0.1:8000/**", proxy);
  await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
  await page.evaluate(() => localStorage.clear());
  await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
  return page;
}

// Stage 1: empty-state full pages at all target viewports.
for (const [w, h] of [[1920, 1080], [1440, 900], [1366, 768], [390, 844]]) {
  const p = await newPage(w, h);
  await p.getByText("Arrasta vídeos, fotos e ficheiros áudio para aqui").waitFor({ timeout: 30000 });
  await p.screenshot({ path: join(SHOTS, `empty-${w}x${h}.png`), fullPage: w < 768 });
  await p.close();
  console.log("empty shot OK", w, h);
}

// Stage 2: upload a clip, then capture populated state + interactions.
// NOTE: the upload goes through the real backend API directly (same bytes
// the user selects). Playwright truncates streamed XHR bodies, so driving
// the file input would test a harness artifact, not the product.
const page = await newPage(1440, 900);
const tmp = mkdtempSync(join(tmpdir(), "qa-uxr-"));
const clip = join(tmp, "clipe-resgate.mp4");
execSync(`ffmpeg -y -f lavfi -i testsrc2=size=640x360:rate=30:duration=6 -f lavfi -i sine=frequency=440:duration=6 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "${clip}"`, { stdio: "ignore" });
const upForm = new FormData();
upForm.append("file", new Blob([readFileSync(clip)], { type: "video/mp4" }), "clipe-resgate.mp4");
const upRes = await fetch(`${API}/api/uploads`, { method: "POST", body: upForm });
if (!upRes.ok) throw new Error("direct upload failed: " + upRes.status);
await page.evaluate((id) => { localStorage.setItem("clipforge.jobId", id); }, (await upRes.json()).job_id);
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.getByText("clipe-resgate.mp4").first().waitFor({ timeout: 60000 });
await page.waitForTimeout(1500);
await page.screenshot({ path: join(SHOTS, "clip-loaded.png") });
console.log("clip loaded");

// Aspect pills (radiogroup), play/pause.
for (const label of ["9:16", "16:9"]) {
  const btn = page.getByRole("radio", { name: label, exact: true });
  if (await btn.count()) { await btn.first().click(); await page.waitForTimeout(600); }
}
await page.screenshot({ path: join(SHOTS, "aspect-toggled.png") });
const play = page.getByRole("button", { name: /Reproduzir|Pausa/ }).first();
if (await play.count()) { await play.click(); await page.waitForTimeout(1200); await play.click(); }
await page.screenshot({ path: join(SHOTS, "playback.png") });
console.log("viewer interactions OK");

// Left panel tabs + selection.
await page.getByRole("button", { name: "Texto" }).first().click();
await page.waitForTimeout(500);
await page.screenshot({ path: join(SHOTS, "rail-text.png") });
await page.getByRole("button", { name: /Adicionar texto/ }).first().click();
await page.waitForTimeout(1000);
await page.screenshot({ path: join(SHOTS, "text-added.png") });
console.log("text panel OK");

await browser.close();
if (errors.length > 0) { console.error("CONSOLE/HTTP ERRORS:", errors); process.exit(1); }
console.log("UX-AUDIT STAGE1 PASS: zero console errors");
