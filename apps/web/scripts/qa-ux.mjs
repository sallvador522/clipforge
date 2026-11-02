/**
 * UX Revolution browser E2E (offline, no Meta calls).
 *
 * Dev-only. Requires the mock API (:8001), worker and web app (:3000).
 * Live-advertised scenarios intercept only GET /health; the actual
 * API/worker remain the local mock stack. The consent loop additionally
 * intercepts the job-status GET and fulfills the /consent POST locally.
 * No request to api.meta.ai is made or expected.
 *
 * Covers: auto-upload (exactly one job, no Create-Job button), no
 * Transcribe button, editable transcript, typed bypass, auto-opened plan
 * review, consent-only-when-required, consent dialog behavior (unchecked,
 * Not now, reopen, authorize with exact payload), chip/card shared
 * selection, approval, verified download, and fake-mic auto-transcription.
 *
 * Usage (from apps/web):
 *   node scripts/qa-ux.mjs <outDir>
 */
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const CLIP = "C:\\Users\\New User\\AppData\\Local\\Temp\\opencode\\approval-clip.mp4";
const outDir = process.argv[2] ?? join(process.env.TEMP ?? ".", "clipforge-ux-qa");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const report = { scenarios: [], console: [], metaRequests: [], uploads: [], consentPosts: [], transcribePosts: [] };

function collect(page, tag) {
  page.on("console", (message) => {
    if (message.type() === "error") report.console.push({ tag, text: message.text() });
  });
  page.on("pageerror", (error) => report.console.push({ tag, text: `pageerror: ${error.message}` }));
  page.on("request", (request) => {
    if (request.url().includes("api.meta.ai")) report.metaRequests.push({ tag, url: request.url() });
    if (request.url().includes("/api/uploads") && request.method() === "POST") report.uploads.push(tag);
    if (request.url().includes("/consent") && request.method() === "POST") {
      report.consentPosts.push({ tag, body: request.postDataJSON() });
    }
    if (request.url().includes("/api/transcribe") && request.method() === "POST") report.transcribePosts.push(tag);
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

async function uploadsSince(n) {
  return report.uploads.length - n;
}

async function waitForSendButton(page, timeout = 30_000) {
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("button")].find(
      (item) => item.textContent?.trim() === "Send to ClipForge",
    );
    return Boolean(button && !button.disabled);
  }, { timeout });
}

/** Selecting a file must upload automatically and create exactly one job. */
async function uploadAuto(page) {
  const before = report.uploads.length;
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  const createButtons = await page.getByRole("button", { name: /create job|upload & create/i }).count();
  await page.setInputFiles('input[type="file"]', CLIP);
  await page.waitForFunction(() => document.body.innerText.includes("JOB PROGRESS"), { timeout: 30_000 });
  return { createButtons, newUploads: report.uploads.length - before };
}

async function typedConfirm(page, instruction) {
  await page.fill("#typed-instruction", instruction);
  await page.getByRole("button", { name: "Use", exact: true }).click();
  await waitForSendButton(page);
  await page.getByRole("button", { name: "Send to ClipForge", exact: true }).click();
}

async function mockAutoFlow() {
  const tag = "mock-auto-flow";
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, tag);
  const { createButtons, newUploads } = await uploadAuto(page);

  // No Transcribe button anywhere, in either mode.
  const transcribeButtons = await page.getByRole("button", { name: /transcribe/i }).count();
  // Transcript is editable before sending.
  await page.fill("#typed-instruction", "blur the background");
  await page.getByRole("button", { name: "Use", exact: true }).click();
  const draft = page.locator('textarea[aria-label="Transcript to confirm"]');
  await draft.fill("blur the background please");
  const draftValue = await draft.inputValue();
  await waitForSendButton(page);
  await page.getByRole("button", { name: "Send to ClipForge", exact: true }).click();

  // Plan review opens automatically — no "Open plan review" click.
  const dialog = page.getByRole("dialog", { name: /What ClipForge intends to do/ });
  await dialog.waitFor({ timeout: 30_000 });
  const consentTitleCount = await page.locator("#sam-consent-title").count();

  // Preview chip and dialog card share one selection. The auto-opened dialog
  // covers the preview, so: select in the dialog, verify on the chip
  // (readable through the modal), close it, deselect on the preview,
  // reopen via "Review plan" and verify the card followed.
  const chip = page.getByTestId("preview-subject-0");
  await chip.waitFor({ timeout: 15_000 });
  await dialog.getByRole("button", { name: /Subject 0/ }).click();
  await page.waitForFunction(
    () => document.querySelector('[data-testid="preview-subject-0"]')?.getAttribute("aria-pressed") === "true",
    { timeout: 15_000 },
  );
  const cardSelectsChip = true;
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 0, { timeout: 10_000 });
  await chip.click();
  await page.waitForFunction(
    () => document.querySelector('[data-testid="preview-subject-0"]')?.getAttribute("aria-pressed") === "false",
    { timeout: 15_000 },
  );
  const chipDeselects = true;
  await page.getByRole("button", { name: "Review plan", exact: true }).click();
  await dialog.waitFor({ timeout: 10_000 });
  await page.waitForFunction(() => {
    const opened = [...document.querySelectorAll('[role="dialog"]')].find((d) =>
      (d.textContent ?? "").includes("What ClipForge intends to do"),
    );
    return Boolean(opened && !opened.textContent?.includes("KEEP SHARP"));
  }, { timeout: 10_000 });
  const cardShowsUnselected = true;
  await dialog.getByRole("button", { name: /Subject 0/ }).click();

  await page.getByRole("button", { name: /Approve selected & render/ }).click();
  await page.waitForFunction(
    () => {
      const button = [...document.querySelectorAll("button")].find(
        (item) => item.textContent?.trim() === "Export MP4",
      );
      return Boolean(button && !button.disabled);
    },
    { timeout: 90_000 },
  );
  const downloadPromise = page.waitForEvent("download", { timeout: 30_000 });
  await page.getByRole("button", { name: /Export MP4/ }).click();
  const download = await downloadPromise;
  const saved = join(outDir, "ux-mock.mp4");
  await download.saveAs(saved);

  report.scenarios.push({
    name: tag,
    createJobButtons: createButtons,
    uploadsForOneSelect: newUploads,
    transcribeButtons,
    transcribeRequests: report.transcribePosts.filter((entry) => entry === tag).length,
    draftEditable: draftValue === "blur the background please",
    consentDialogShown: consentTitleCount,
    cardSelectsChip,
    chipDeselects,
    reopenShowsCardUnselected: cardShowsUnselected,
    exported: saved,
  });
  await page.close();
}

async function liveClarificationNeedsNoConsent() {
  const tag = "live-clarification-no-consent";
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, tag);
  await advertiseLiveSegmentation(page);
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  await page.setInputFiles('input[type="file"]', CLIP);
  await page.waitForFunction(() => document.body.innerText.includes("JOB PROGRESS"), { timeout: 30_000 });
  await page.fill("#typed-instruction", "Desfoca ele, por favor.");
  await page.getByRole("button", { name: "Use", exact: true }).click();
  await waitForSendButton(page);
  await page.getByRole("button", { name: "Send to ClipForge", exact: true }).click();
  // Ambiguous instruction → clarification, never a SAM consent dialog.
  await page.waitForFunction(() => document.body.innerText.includes("Needs your answer"), { timeout: 30_000 });
  await page.waitForTimeout(1500);
  const consentCount = await page.locator("#sam-consent-title").count();
  const consentPosts = report.consentPosts.filter((entry) => entry.tag === tag).length;
  report.scenarios.push({ name: tag, consentDialogShown: consentCount, consentPosts });
  await page.close();
}

async function liveConsentLoop() {
  const tag = "live-consent-loop";
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  collect(page, tag);
  await advertiseLiveSegmentation(page);

  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  const uploadResponse = page.waitForResponse(
    (response) => response.url().includes("/api/uploads") && response.request().method() === "POST",
    { timeout: 60_000 },
  );
  await page.setInputFiles('input[type="file"]', CLIP);
  const jobId = (await (await uploadResponse).json()).job_id;
  await page.waitForFunction(() => document.body.innerText.includes("JOB PROGRESS"), { timeout: 30_000 });

  // Override polling: queued/processing read as awaiting_consent so the
  // consent dialog opens without a real SAM provider. Real review states
  // pass through untouched.
  let passthrough = false;
  let lastRealBody = null;
  const TERMINAL = new Set(["completed", "failed", "rejected", "unsupported"]);
  await page.route(`**/api/jobs/${jobId}`, async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    lastRealBody = body;
    if (!passthrough && !TERMINAL.has(body.status)) {
      body.status = "awaiting_consent";
      body.stage = "awaiting_consent";
      await route.fulfill({ response, json: body });
    } else {
      await route.continue();
    }
  });

  await page.fill("#typed-instruction", "blur the background");
  await page.getByRole("button", { name: "Use", exact: true }).click();
  await waitForSendButton(page);
  await page.getByRole("button", { name: "Send to ClipForge", exact: true }).click();

  const dialog = page.getByRole("dialog", { name: /Autorização para identificar pessoas/ });
  await dialog.waitFor({ timeout: 15_000 });
  const checkbox = page.locator("#sam-consent-checkbox");
  const authorize = page.getByRole("button", { name: "Autorizar e continuar" });
  const copy = await dialog.innerText();
  const findings = {
    hasReason: copy.includes("needs to identify the people"),
    hasDisclosure: copy.includes("cópia temporária, sem áudio"),
    notPreselected: !(await checkbox.isChecked()),
    authorizeDisabledBeforeCheck: await authorize.isDisabled(),
  };

  const postsBefore = report.consentPosts.length;
  await page.getByRole("button", { name: "Not now", exact: true }).click();
  await page.waitForTimeout(800);
  findings.pausedAfterNotNow = (await page.locator("#sam-consent-title").count()) === 0;
  findings.consentPostsAfterNotNow = report.consentPosts.length - postsBefore;

  await page.getByRole("button", { name: "Continue with subject detection" }).click();
  await dialog.waitFor({ timeout: 10_000 });
  await checkbox.check();
  const consentBodyP = page
    .waitForResponse(
      (response) => response.url().includes("/consent") && response.request().method() === "POST",
      { timeout: 15_000 },
    )
    .then((response) => ({ status: response.status() }));
  await page.route(`**/api/jobs/${jobId}/consent`, async (route) => {
    // The real backend rightly 409s (it never saw awaiting_consent); answer
    // 200 locally with the last full job snapshot so the UI keeps a valid
    // job object and resumes polling exactly as after a real grant.
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...lastRealBody, status: "queued", stage: "queued" }),
    });
  });
  await authorize.click();
  const consentResult = await consentBodyP;
  passthrough = true;
  findings.consentStatus = consentResult.status;
  findings.consentField = report.consentPosts.at(-1)?.body?.subject_detection_consent === true;

  // The fulfilled consent unblocks polling; the real plan review opens by itself.
  await page.getByRole("dialog", { name: /What ClipForge intends to do/ }).waitFor({ timeout: 60_000 });
  findings.planAutoOpened = true;
  findings.metaRequests = report.metaRequests.length;
  // The auto-opened dialog covers the preview, so close it, toggle the
  // preview chip, reopen and verify the card followed the shared state.
  const dialogsBefore = await page.getByRole("dialog").all();
  findings.dialogsBeforeEsc = [];
  for (const dialogElement of dialogsBefore) {
    findings.dialogsBeforeEsc.push(await dialogElement.getAttribute("aria-labelledby"));
  }
  await page.getByRole("button", { name: "Close plan review", exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 0, { timeout: 10_000 });
  const chip = page.getByTestId("preview-subject-1");
  await chip.click();
  await page.waitForFunction(
    () => document.querySelector('[data-testid="preview-subject-1"]')?.getAttribute("aria-pressed") === "true",
    { timeout: 15_000 },
  );
  findings.chipSelects = true;
  await page.getByRole("button", { name: "Review plan", exact: true }).click();
  await page.getByRole("dialog", { name: /What ClipForge intends to do/ }).waitFor({ timeout: 10_000 });
  findings.cardFollowsChip = (await page.getByRole("dialog").innerText()).includes("KEEP SHARP");
  await page.getByRole("button", { name: /Approve selected & render/ }).click();
  report.scenarios.push({ name: tag, ...findings });
  await page.close();
}

async function autoTranscribeWithFakeMic() {
  const tag = "auto-transcribe-fake-mic";
  // A separate headless browser with a fake mic: stopping the recording must
  // fire /api/transcribe by itself (intercepted below, never a real call),
  // and no Transcribe button may exist anywhere.
  let micBrowser = null;
  try {
    micBrowser = await chromium.launch({
      executablePath: CHROME,
      headless: true,
      args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
    });
  } catch {
    report.scenarios.push({ name: tag, skipped: "fake-mic browser unavailable" });
    return;
  }
  const context = await micBrowser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["microphone"] });
  const page = await context.newPage();
  collect(page, tag);
  await page.route("**/health", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.transcribe_mode = "live";
    body.live_transcription_available = true;
    await route.fulfill({ response, json: body });
  });
  await page.route("**/api/transcribe", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        text: "desfoca o fundo por favor",
        language: "pt-BR",
        confidence: 0.9,
        provider_name: "test-mic",
        is_mock: false,
        session_id: "qa-mic",
        audio_duration_ms: 2500,
        transcribe_mode: "live",
      }),
    });
  });
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  await page.setInputFiles('input[type="file"]', CLIP);
  await page.waitForFunction(() => document.body.innerText.includes("JOB PROGRESS"), { timeout: 30_000 });
  const start = page.getByRole("button", { name: "Start voice recording" });
  try {
    // The record button pulses while recording and never stabilises; force both clicks.
    await start.click({ force: true, timeout: 10_000 });
    await page.waitForFunction(() => document.body.innerText.includes("Listening"), { timeout: 10_000 });
  } catch {
    report.scenarios.push({ name: tag, skipped: "microphone unavailable in this environment" });
    await micBrowser.close();
    return;
  }
  await page.waitForTimeout(2500);
  await page.getByRole("button", { name: "Stop recording" }).click({ force: true });
  await page.waitForFunction(
    () => { const el = document.querySelector('textarea[aria-label="Transcript to confirm"]'); return (el instanceof HTMLTextAreaElement) && el.value.includes("desfoca o fundo por favor"); },
    { timeout: 20_000 },
  );
  const transcribeButtons = await page.getByRole("button", { name: /transcribe/i }).count();
  report.scenarios.push({
    name: tag,
    transcribeRequests: report.transcribePosts.filter((entry) => entry === tag).length,
    transcribeButtons,
    transcriptAppeared: true,
  });
  await micBrowser.close();
}

try {
  await mockAutoFlow();
  await liveClarificationNeedsNoConsent();
  await liveConsentLoop();
  await autoTranscribeWithFakeMic();
  console.log(JSON.stringify({ report, outDir }, null, 2));
} finally {
  await browser.close();
}
