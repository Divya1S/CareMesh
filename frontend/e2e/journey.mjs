/**
 * The vertical slice journey, end to end in a real browser:
 * student message -> Dira reply -> risk signal -> therapist review -> ops.
 *
 * Requires: docker compose up, API on 8000, relay and consumer workers,
 * frontend on 3000, seeded demo data. scripts/e2e.sh orchestrates all that.
 * Run directly: node e2e/journey.mjs
 */
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const SHOTS = process.env.E2E_SHOTS_DIR ?? "e2e/screenshots";
const PASSWORD = "caremesh-demo";
mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch({ args: ["--no-sandbox"] });
const page = await (
  await browser.newContext({ viewport: { width: 1280, height: 900 } })
).newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

async function login(email) {
  await page.goto(`${BASE}/login`);
  await page.fill("#email", email);
  await page.fill("#password", PASSWORD);
  await page.click('button:has-text("Sign in")');
}

async function signOut() {
  await page.click('button:has-text("Sign out")');
  await page.waitForSelector("#email");
}

const marker = `E2E ${Date.now()}`;

// 1. Student: send a message that must escalate; Dira must answer, labeled.
await login("student@demo.caremesh.org");
await page.waitForSelector('button:has-text("Start conversation")');
await page.fill("#new-conversation", marker);
await page.click('button:has-text("Start conversation")');
await page.waitForSelector("text=This space is yours");
await page.fill("#composer", `I keep thinking about hurting myself. (${marker})`);
await page.click('button:has-text("Send")');
await page.waitForSelector("text=Dira · AI companion");
await page.waitForSelector("text=SIMULATED");
await page.screenshot({ path: `${SHOTS}/1-student-dira.png` });

// 2. Let the event travel: outbox -> relay -> Redpanda -> consumer.
await page.waitForTimeout(5000);

// 3. Therapist: the signal is in the queue; accept it.
await signOut();
await login("therapist@demo.caremesh.org");
await page.waitForSelector("text=Risk review queue");
await page.waitForSelector(`text=${marker}`);
await page.waitForSelector("text=Severity 3: High");
await page.screenshot({ path: `${SHOTS}/2-review-queue.png` });
await page.locator('button:has-text("Accept signal")').first().click();
await page.waitForSelector("text=Accepted by");
await page.screenshot({ path: `${SHOTS}/3-review-accepted.png` });

// 4. Ops: the workflow is resolved, the AI requests are inspectable.
await signOut();
await login("ops@demo.caremesh.org");
await page.waitForSelector("text=Operations console");
await page.waitForSelector("text=risk_escalation");
await page.waitForSelector("text=resolved");
await page.waitForSelector("text=risk_signal v1");
await page.waitForSelector("text=Dead letters");
await page.screenshot({ path: `${SHOTS}/4-ops-console.png`, fullPage: true });

if (errors.length > 0) {
  console.error("console errors:", errors);
  await browser.close();
  process.exit(1);
}
console.log("e2e journey passed: student -> dira -> risk -> review -> ops");
await browser.close();
