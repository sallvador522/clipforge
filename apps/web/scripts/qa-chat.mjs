import { chromium } from "playwright-core";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const API = "http://127.0.0.1:8001";
const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

// Isolate from the other session's :8000 stack: proxy every API call to :8001.
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

await page.goto("http://127.0.0.1:3001/", { waitUntil: "networkidle", timeout: 60000 });
// Fresh conversation: drop any idea/job restored from a previous run so the
// composer starts enabled (canConfirm blocks mid-flow ideas by design).
await page.evaluate(() => window.localStorage.clear());
await page.evaluate(() => window.localStorage.clear());
// Reload on the bare URL: a previous run leaves ?idea= in the address bar,
// which would restore that idea from the backend and (by design) lock the
// composer until the idea flow resolves.
await page.goto("http://127.0.0.1:3001/", { waitUntil: "networkidle", timeout: 60000 });

const box = page.getByLabel("Mensagem para o Muse");
await box.waitFor({ timeout: 30000 });

// 1. ola -> smalltalk reply, no Executar card
await box.fill("ola");
await page.getByLabel("Enviar para o Muse").click();
await page.waitForFunction(
  () => document.body.textContent?.includes("Posso desfocar o fundo"),
  null, { timeout: 30000 },
);
const hasExecuteAfterOla = await page.getByRole("button", { name: "Executar" }).count();
console.log(JSON.stringify({ ola_reply_ok: true, execute_cards_after_ola: hasExecuteAfterOla }));

// 2. idea request -> director interview (ADR-048) -> proposal -> Executar card
await box.fill("cria um video sobre o mar");
await page.getByLabel("Enviar para o Muse").click();
await page.getByRole("group", { name: "Que estilo queres para o vídeo?" }).waitFor({ timeout: 30000 });
await page.getByRole("button", { name: "Documental" }).click();
await page.getByRole("group", { name: "Qual a duração?" }).getByRole("button", { name: "30s" }).click({ timeout: 30000 });
await page.getByRole("button", { name: "Vertical 9:16" }).click({ timeout: 30000 });
await page.getByRole("button", { name: "Executar" }).waitFor({ timeout: 30000 });
console.log(JSON.stringify({ idea_proposal_card_ok: true }));

// 3. Executar creates the idea (mock, no paid call) — the idea panel asks
// for the storyboard cost approval; no worker runs on this isolated stack.
await page.getByRole("button", { name: "Executar" }).click();
await page.waitForFunction(
  () => document.body.textContent?.includes("Aprova o custo") || document.body.textContent?.includes("aprovação do plano"),
  null, { timeout: 60000 },
);
console.log(JSON.stringify({ idea_executed_ok: true }));

console.log(JSON.stringify({ console_errors: errors }));
await browser.close();
if (errors.length > 0) process.exit(2);
