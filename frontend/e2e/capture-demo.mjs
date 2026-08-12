/**
 * Records the demo video for the README: student chat with streaming and
 * tool use, the crisis flow into the clinician review queue, and the ops
 * console. Produces a webm in e2e/recordings/ that scripts turn into the
 * README gif. Same stack requirements as journey.mjs.
 */
import { mkdirSync, readdirSync, renameSync } from "node:fs";
import { chromium } from "playwright";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const OUT = "e2e/recordings";
const PASSWORD = "caremesh-demo";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ args: ["--no-sandbox"] });
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  recordVideo: { dir: OUT, size: { width: 1280, height: 800 } },
});
const page = await context.newPage();

async function login(email) {
  await page.goto(`${BASE}/login`);
  await page.waitForSelector("#email");
  await page.fill("#email", email);
  await page.fill("#password", PASSWORD);
  await page.waitForTimeout(600);
  await page.click('button:has-text("Sign in")');
}

async function signOut() {
  await page.click('button:has-text("Sign out")');
  await page.waitForSelector("#email");
}

const marker = `Demo ${Date.now()}`;

// Scene 1: student chat. A resource question first (tool use + streaming),
// then a crisis message (tools structurally bypassed, direct crisis reply).
await login("student@demo.caremesh.org");
await page.waitForSelector('button:has-text("Start conversation")');
await page.fill("#new-conversation", marker);
await page.click('button:has-text("Start conversation")');
await page.waitForSelector("text=This space is yours");
await page.fill("#composer", "any tips for sleeping better before exams?");
await page.click('button:has-text("Send")');
await page.waitForSelector("text=Dira · AI companion");
await page.waitForSelector("text=SIMULATED");
await page.waitForTimeout(2500);
await page.fill("#composer", `I keep thinking about hurting myself. (${marker})`);
await page.click('button:has-text("Send")');
await page.waitForSelector("text=crisis resources");
await page.waitForTimeout(3000);

// Let the event travel: outbox -> relay -> Redpanda -> consumer.
await page.waitForTimeout(4000);

// Scene 2: therapist review queue, accept the escalated signal.
await signOut();
await login("therapist@demo.caremesh.org");
await page.waitForSelector("text=Risk review queue");
await page.waitForSelector(`text=${marker}`);
await page.waitForTimeout(2000);
await page.locator('button:has-text("Accept signal")').first().click();
await page.waitForSelector("text=Accepted by");
await page.waitForTimeout(2500);

// Scene 3: ops console, workflows and the AI request inspector.
await signOut();
await login("ops@demo.caremesh.org");
await page.waitForSelector("text=Operations console");
await page.waitForSelector("text=risk_escalation");
await page.waitForTimeout(2000);
await page.waitForSelector("text=risk_signal v1");
await page.waitForTimeout(2500);

await context.close();
await browser.close();

// Playwright names the file with a hash; give it a stable name.
const video = readdirSync(OUT).find((f) => f.endsWith(".webm"));
renameSync(`${OUT}/${video}`, `${OUT}/demo.webm`);
console.log(`recorded ${OUT}/demo.webm`);
