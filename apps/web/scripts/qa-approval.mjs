/**
 * Milestone 6C browser E2E: review -> approve/reject/clarify -> render -> export.
 * Dev-only. Requires the mock API, worker and web app on localhost:3000.
 *
 * Usage (from apps/web):
 *   node scripts/qa-approval.mjs <outDir>
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const CLIP = "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\approval-clip.mp4";
const outDir = process.argv[2] ?? join(process.env.TEMP ?? ".", "clipforge-approval-qa");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const report = { scenarios: [], console: [] };

function collect(page, tag) {
  page.on("console", (m) => {
    if (m.type() === "error") report.console.push({ tag, text: m.text() });
  });
  page.on("pageerror", (e) => report.console.push({ tag, text: `pageerror: ${e.message}` }));
}

async function waitForExportEnabled(page, timeout = 60_000) {
  await page.waitForFunction(
    () => {
      const button = [...document.querySelectorAll("button")].find(
        (b) => b.textContent?.trim() === "Export MP4",
      );
      return Boolean(button && !button.disabled);
    },
    { timeout },
  );
}

async function uploadAndConfirm(page, instruction) {
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  await page.setInputFiles('input[type="file"]', CLIP);
  await page.waitForFunction(() => document.body.innerText.includes("JOB PROGRESS"), { timeout: 30_000 });
  await page.fill("#typed-instruction", instruction);
  await page.getByRole("button", { name: "Use" }).click();
  await page.getByRole("button", { name: /Send to ClipForge/ }).click();
}

async function exportVideo(page, filename) {
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export MP4" }).click();
  const download = await downloadPromise;
  const path = join(outDir, filename);
  await download.saveAs(path);
  return path;
}

async function selectFirstSubject(page) {
  await page.getByRole("button", { name: /Subject 0/ }).first().click();
}

async function blurScenario(viewport, name) {
  const page = await browser.newPage({ viewport });
  collect(page, name);
  await uploadAndConfirm(page, "blur the background");
  await page.getByRole("dialog").waitFor({ timeout: 20_000 });
  const operations = await page.locator('[role="dialog"] li').count();
  const dialogText = await page.getByRole("dialog").innerText();
  const hasMockMask = dialogText.includes("MOCK");
  const hasSubjects = dialogText.includes("DETECTED PEOPLE");
  const previews = page.locator('[role="dialog"] img');
  const previewCount = await previews.count();
  await previews.first().waitFor({ state: "visible" });
  const previewWidth = await previews.first().evaluate((img) => img.naturalWidth);
  await selectFirstSubject(page);
  await page.getByRole("button", { name: /Approve selected & render/ }).click();
  await waitForExportEnabled(page);
  const saved = await exportVideo(page, `${name}.mp4`);
  report.scenarios.push({
    name,
    result: "completed",
    operations,
    hasMockMask,
    hasSubjects,
    previewCount,
    previewWidth,
    saved,
  });
  await page.close();
}

async function replacementScenario() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, "replacement");
  await uploadAndConfirm(page, "Substitui o fundo por um estúdio profissional.");
  await page.getByRole("dialog").waitFor({ timeout: 20_000 });
  const text = await page.getByRole("dialog").innerText();
  const exportBefore = await page.getByRole("button", { name: "Export MP4" }).isEnabled();
  await selectFirstSubject(page);
  await page.getByRole("button", { name: /Approve selected & render/ }).click();
  await waitForExportEnabled(page);
  const saved = await exportVideo(page, "replacement.mp4");
  report.scenarios.push({
    name: "replacement",
    result: "completed",
    approvalRequired: text.includes("DETECTED PEOPLE"),
    exportBeforeApproval: exportBefore,
    saved,
  });
  await page.close();
}

async function rejectScenario() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, "reject");
  await uploadAndConfirm(page, "blur the background");
  await page.getByRole("dialog").waitFor({ timeout: 20_000 });
  await page.getByRole("button", { name: "Reject plan" }).click();
  await page.getByText("Plan rejected", { exact: false }).waitFor({ timeout: 10_000 });
  const exportEnabled = await page.getByRole("button", { name: "Export MP4" }).isEnabled();
  report.scenarios.push({ name: "reject", result: "rejected", exportEnabled });
  await page.close();
}

async function clarificationScenario() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, "clarification");
  await uploadAndConfirm(page, "Desfoca ele, por favor.");
  await page.getByRole("dialog").waitFor({ timeout: 20_000 });
  await page.fill("#clarification-answer", "Mantém o homem da esquerda nítido.");
  await page.getByRole("button", { name: "Answer & rebuild plan" }).click();
  await page.getByRole("dialog").waitFor({ timeout: 20_000 });
  await selectFirstSubject(page);
  await page.getByRole("button", { name: /Approve selected & render/ }).click();
  await waitForExportEnabled(page);
  const saved = await exportVideo(page, "clarification.mp4");
  report.scenarios.push({ name: "clarification", result: "completed", saved });
  await page.close();
}

async function unsupportedScenario() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, "unsupported");
  await uploadAndConfirm(page, "Adiciona legendas amarelas ao vídeo.");
  await page.getByText("Request not supported", { exact: false }).waitFor({ timeout: 20_000 });
  const exportEnabled = await page.getByRole("button", { name: "Export MP4" }).isEnabled();
  report.scenarios.push({ name: "unsupported", result: "unsupported", exportEnabled });
  await page.close();
}

try {
  await blurScenario({ width: 1440, height: 900 }, "blur-desktop");
  await blurScenario({ width: 390, height: 844 }, "blur-mobile");
  await replacementScenario();
  await rejectScenario();
  await clarificationScenario();
  await unsupportedScenario();
  console.log(JSON.stringify({ report, outDir }, null, 2));
} finally {
  await browser.close();
}
