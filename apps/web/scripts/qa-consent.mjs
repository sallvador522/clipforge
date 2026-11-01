/**
 * Milestone 6D consent-gate browser E2E.
 *
 * Dev-only. Requires the mock API (:8001), worker and web app (:3000).
 * The live consent scenarios intercept only GET /health to advertise
 * segmentation_mode="live"; the actual API/worker remain the local mock stack.
 * No request to api.meta.ai is made or expected.
 *
 * Usage (from apps/web):
 *   node scripts/qa-consent.mjs <outDir>
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const CLIP = "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\approval-clip.mp4";
const outDir = process.argv[2] ?? join(process.env.TEMP ?? ".", "clipforge-consent-qa");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const report = { scenarios: [], console: [], metaRequests: [] };

function collect(page, tag) {
  page.on("console", (message) => {
    if (message.type() === "error") report.console.push({ tag, text: message.text() });
  });
  page.on("pageerror", (error) => report.console.push({ tag, text: `pageerror: ${error.message}` }));
  page.on("request", (request) => {
    if (request.url().includes("api.meta.ai")) {
      report.metaRequests.push({ tag, url: request.url() });
    }
  });
}

async function advertiseLiveSegmentation(page) {
  await page.route("**/health", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.segmentation_mode = "live";
    await route.fulfill({ response, json: body });
  });
}

async function uploadAndConfirm(page, instruction) {
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  await page.setInputFiles('input[type="file"]', CLIP);
  await page.getByRole("button", { name: /Upload & create job/ }).click();
  await page.waitForFunction(() => document.body.innerText.includes("Uploaded — job created"));
  await page.fill("#typed-instruction", instruction);
  await page.getByRole("button", { name: "Use" }).click();
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("button")].find((item) =>
      item.textContent?.includes("Confirm transcript & start editing"),
    );
    return Boolean(button && !button.disabled);
  });
  await page.getByRole("button", { name: /Confirm transcript & start editing/ }).click();
}

function voiceRequest(page, collector) {
  page.on("request", (request) => {
    if (request.url().includes("/voice") && request.method() === "POST") collector.push(request);
  });
}

async function completePlanAndExport(page) {
  await page.getByText("DETECTED PEOPLE", { exact: false }).waitFor({ timeout: 30_000 });
  await page.getByRole("button", { name: /Subject 0/ }).first().click();
  await page.getByRole("button", { name: /Approve selected & render/ }).click();
  await page.waitForFunction(
    () => {
      const button = [...document.querySelectorAll("button")].find(
        (item) => item.textContent?.trim() === "Export MP4",
      );
      return Boolean(button && !button.disabled);
    },
    { timeout: 60_000 },
  );
}

async function liveDesktopScenario() {
  const tag = "consent-live-desktop";
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, tag);
  await advertiseLiveSegmentation(page);
  const requests = [];
  voiceRequest(page, requests);
  await uploadAndConfirm(page, "blur the background");

  const dialog = page.getByRole("dialog", { name: /Autorização para identificar pessoas/ });
  await dialog.waitFor({ timeout: 10_000 });
  const copy = await dialog.innerText();
  const checkbox = page.locator("#sam-consent-checkbox");
  const authorize = page.getByRole("button", { name: "Autorizar e continuar" });
  const notPreselected = !(await checkbox.isChecked());
  const disabledBeforeCheck = await authorize.isDisabled();
  const hasDisclosure =
    copy.includes("cópia temporária, sem áudio") &&
    copy.includes("expire automaticamente após uma hora") &&
    copy.includes("antes de apresentarmos o teu plano de edição") &&
    copy.includes("autorizas este processamento externo");
  const noFalseClaims =
    !copy.includes("apenas no teu dispositivo") &&
    !copy.includes("garantida") &&
    !copy.includes("eliminada imediatamente");

  await page.getByRole("button", { name: "Cancelar" }).click();
  await page.waitForTimeout(700);
  const afterDeclineRequests = requests.length;
  const dialogAfterDecline = await page.locator("#sam-consent-title").count();

  await page.getByRole("button", { name: /Confirm transcript & start editing/ }).click();
  await checkbox.check();
  await authorize.click();
  await page.waitForFunction(() => document.querySelector("#sam-consent-title") === null, {
    timeout: 10_000,
  });
  const consentField = requests.length > 0 ? requests.at(-1).postDataJSON()?.subject_detection_consent : null;
  await completePlanAndExport(page);

  report.scenarios.push({
    name: tag,
    notPreselected,
    disabledBeforeCheck,
    hasDisclosure,
    noFalseClaims,
    afterDeclineRequests,
    dialogAfterDecline,
    consentField,
    voiceRequests: requests.length,
    metaRequests: report.metaRequests.length,
  });
  await page.close();
}

async function liveMobileScenario() {
  const tag = "consent-live-mobile";
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  collect(page, tag);
  await advertiseLiveSegmentation(page);
  const requests = [];
  voiceRequest(page, requests);
  await uploadAndConfirm(page, "blur the background");

  const dialog = page.getByRole("dialog", { name: /Autorização para identificar pessoas/ });
  await dialog.waitFor({ timeout: 10_000 });
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize();
  const inViewport = Boolean(
    box && viewport && box.x >= 0 && box.y >= 0 && box.x + box.width <= viewport.width + 1,
  );
  const checkboxVisible = await page.locator("#sam-consent-checkbox").isVisible();
  const authorizeVisible = await page.getByRole("button", { name: "Autorizar e continuar" }).isVisible();
  const cancelVisible = await page.getByRole("button", { name: "Cancelar" }).isVisible();
  await page.getByRole("button", { name: "Cancelar" }).click();
  await page.waitForTimeout(500);
  report.scenarios.push({
    name: tag,
    inViewport,
    checkboxVisible,
    authorizeVisible,
    cancelVisible,
    voiceRequestsAfterDecline: requests.length,
  });
  await page.close();
}

async function mockModeScenario() {
  const tag = "consent-mock-no-dialog";
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, tag);
  const requests = [];
  voiceRequest(page, requests);
  await uploadAndConfirm(page, "blur the background");

  const dialogCount = await page.locator("#sam-consent-title").count();
  await page.getByText("DETECTED PEOPLE", { exact: false }).waitFor({ timeout: 30_000 });
  const consentField = requests.length > 0 ? requests.at(-1).postDataJSON()?.subject_detection_consent : "missing";
  report.scenarios.push({
    name: tag,
    dialogCount,
    voiceRequests: requests.length,
    consentField: consentField ?? null,
  });
  await page.close();
}

try {
  await liveDesktopScenario();
  await liveMobileScenario();
  await mockModeScenario();
  console.log(JSON.stringify({ report, outDir }, null, 2));
} finally {
  await browser.close();
}
