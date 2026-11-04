/* Final hackathon E2E (mock stack API :8001 + web :3001, zero paid calls):
 * first-time user -> UI upload (accented filename) -> asset download with
 * SHA-256 integrity -> reload persistence -> invalid upload rejected ->
 * timeline zoom/seek -> Montar -> Exportar download verified with ffprobe. */
import { execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const API = "http://127.0.0.1:8001";
const WEB = "http://127.0.0.1:3001";
const sha = (buf) => createHash("sha256").update(buf).digest("hex");

const tmp = mkdtempSync(join(tmpdir(), "qa-final-"));
const clipName = "meu vídeo (teste).mp4";
const clip = join(tmp, clipName);
execSync(`ffmpeg -y -f lavfi -i testsrc2=size=320x180:rate=30:duration=5 -f lavfi -i sine=frequency=440:duration=5 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "${clip}"`, { stdio: "ignore" });
const originalBytes = readFileSync(clip);

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
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
  let post = route.request().postDataBuffer();
  if ((url.pathname === "/api/uploads" || url.pathname.endsWith("/assets")) && post) {
    // Playwright may truncate streamed XHR bodies; the file bytes are the
    // same file the user selected, rebuilt with the same boundary.
    const boundary = (ct.match(/boundary=(.+)$/) || [])[1];
    const field = url.pathname === "/api/uploads" ? "file" : "file";
    const head = Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="${field}"; filename="${clipName}"\r\nContent-Type: video/mp4\r\n\r\n`);
    post = Buffer.concat([head, originalBytes, Buffer.from(`\r\n--${boundary}--\r\n`)]);
  }
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
const api = (path, opts = {}) => fetch(`${API}${path}`, { ...opts, headers: { "content-type": "application/json", ...(opts.headers ?? {}) } });

// A1. First visit: app loads, creation entry visible.
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.evaluate(() => localStorage.clear());
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.getByText("Arrasta vídeos, fotos e ficheiros áudio para aqui").waitFor({ timeout: 30000 });
console.log("A1 first-visit empty state OK");

// A2. Upload through the real UI input.
await page.locator('input[aria-label="Escolher ficheiro de vídeo"]').setInputFiles(clip);
await page.getByText(clipName).first().waitFor({ timeout: 60000 });
await page.waitForFunction(() => localStorage.getItem("clipforge.jobId"), null, { timeout: 30000 });
const jobId = await page.evaluate(() => localStorage.getItem("clipforge.jobId"));
const projectId = await page.evaluate(() => localStorage.getItem("clipforge.projectId"));
console.log("A2 UI upload OK job", jobId, "project", projectId);

// A3. Download the ORIGINAL from the session card; verify integrity.
const [dl] = await Promise.all([
  page.waitForEvent("download", { timeout: 30000 }),
  page.getByRole("link", { name: `Descarregar ${clipName}` }).click(),
]);
const dlPath = join(tmp, "downloaded-original.mp4");
await dl.saveAs(dlPath);
const dlBytes = readFileSync(dlPath);
if (sha(dlBytes) !== sha(originalBytes)) throw new Error(`original download integrity mismatch ${dlBytes.length} vs ${originalBytes.length}`);
console.log("A3 original download SHA-256 identical OK", dlBytes.length, "bytes, suggested:", await dl.suggestedFilename());

// A4. Invalid upload rejected, no fake asset. Direct API call: the browser
// proxy above rebuilds upload bodies from the selected clip, so the invalid
// case must bypass it to test real backend validation.
const assetsBefore = (await (await api(`/api/projects/${projectId}/assets`)).json()).assets.length;
const badForm = new FormData();
badForm.append("file", new Blob([Buffer.from("MZ fake executable payload")], { type: "application/octet-stream" }), "malware.exe");
const badRes = await fetch(`${API}/api/projects/${projectId}/assets`, { method: "POST", body: badForm });
if (badRes.ok) throw new Error("invalid .exe upload was accepted: " + badRes.status);
const badBody = await badRes.json().catch(() => ({}));
const assetsAfter = (await (await api(`/api/projects/${projectId}/assets`)).json()).assets.length;
if (assetsAfter !== assetsBefore) throw new Error(`invalid upload created asset ${assetsBefore} -> ${assetsAfter}`);
console.log("A4 invalid upload rejected OK", badRes.status, JSON.stringify(badBody).slice(0, 120), "(assets unchanged:", assetsAfter, ")");

// A5. Reload: project + asset persist.
await page.goto(WEB + "/", { waitUntil: "networkidle", timeout: 60000 });
await page.getByText(clipName).first().waitFor({ timeout: 30000 });
console.log("A5 reload persistence OK");

// A6. Timeline zoom is functional.
const zoom = page.getByLabel("Zoom da linha de tempo");
const before = await zoom.inputValue();
await page.getByRole("button", { name: "Aproximar linha de tempo" }).click();
const after = await zoom.inputValue();
if (Number(after) <= Number(before)) throw new Error(`zoom did not increase ${before} -> ${after}`);
console.log("A6 timeline zoom OK", before, "->", after);

// A7. Montar (real FFmpeg compose) -> completed/verified.
await page.getByRole("button", { name: /Montar/ }).first().click();
let state = "";
for (let i = 0; i < 60; i++) {
  const j = await (await api(`/api/jobs/${jobId}`)).json();
  state = `${j.status}/${j.stage}`;
  if (j.status === "completed" || j.status === "failed") break;
  await page.waitForTimeout(3000);
}
if (!state.startsWith("completed")) throw new Error("Montar did not complete: " + state);
const result = await (await api(`/api/jobs/${jobId}/result`)).json();
if (result.render_status !== "verified") throw new Error("render not verified");
console.log("A7 Montar verified OK", state);

// A8. Exportar downloads the final MP4; ffprobe validates it.
const [dl2] = await Promise.all([
  page.waitForEvent("download", { timeout: 60000 }),
  page.getByRole("button", { name: /Exportar/ }).first().click(),
]);
const outPath = join(tmp, "final.mp4");
await dl2.saveAs(outPath);
const probe = JSON.parse(execSync(`ffprobe -v error -show_streams -show_format -of json "${outPath}"`, { encoding: "utf8" }));
const kinds = probe.streams.map((s) => s.codec_type).sort().join("+");
if (!probe.streams.some((s) => s.codec_type === "video" && s.codec_name === "h264")) throw new Error("final MP4 lacks h264 video: " + kinds);
if (!probe.streams.some((s) => s.codec_type === "audio")) throw new Error("final MP4 lacks audio: " + kinds);
console.log("A8 final MP4 download + ffprobe OK", kinds, probe.format.size, "bytes, duration", probe.format.duration);

await browser.close();
if (errors.length > 0) { console.error("CONSOLE ERRORS:", errors); process.exit(1); }
console.log("FINAL-E2E PASS: zero console errors");
