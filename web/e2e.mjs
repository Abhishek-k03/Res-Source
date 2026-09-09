/**
 * Click-through check of the whole product in a real browser.
 *
 *   node e2e.mjs
 *
 * Expects the API on :8000, the worker running, and `npm run dev` on :3000.
 */
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";

const WEB = "http://localhost:3000";
const STAMP = Date.now().toString().slice(-6);
const NAME = `E2E ${STAMP}`;
const SLUG = `e2e-${STAMP}`;
const results = [];

function check(name, ok, detail = "") {
  results.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` — ${detail}` : ""}`);
}

const RAFT = `# Raft Consensus

Raft elects a single leader per term. A follower receiving no heartbeat within
its election timeout becomes a candidate, increments the term, and requests
votes. A candidate wins on votes from a majority of the cluster. A server grants
its vote only to a candidate whose log is at least as up to date as its own.

Log replication flows only from the leader to followers. The leader appends a
command and sends AppendEntries in parallel; once stored on a majority the
leader commits the entry and applies it to its state machine.
`;

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
page.on("dialog", (d) => d.accept());

try {
  // --- shell ------------------------------------------------------------
  await page.goto(WEB, { waitUntil: "networkidle" });
  check(
    "brand renders",
    (await page.locator(".brand-name").textContent()) === "Res-Source",
  );
  await page.locator(".sidebar-foot").waitFor({ timeout: 15000 });
  const healthText = await page.locator(".sidebar-foot").textContent();
  check("service health is shown", /healthy/.test(healthText ?? ""), healthText?.trim());

  // --- create a collection ---------------------------------------------
  await page.click('.nav-add:has-text("+ New")');
  await page.waitForSelector('h1:has-text("Create a research collection")', {
    timeout: 15000,
  });
  check("ingest screen opens", true);

  await page.fill('input[placeholder="Sleep & Memory Consolidation"]', NAME);
  await page.fill('input[placeholder^="what this corpus"]', "distributed consensus");
  const slugPreview = await page.locator("main .mono").first().textContent();
  check("slug is derived from the name", slugPreview?.trim() === SLUG, slugPreview?.trim());

  await page.click('button:has-text("Create collection")');
  await page.waitForSelector(`h1:has-text("${NAME}")`, { timeout: 20000 });
  check("collection is created and opened", true);
  check(
    "it appears in the sidebar",
    await page.locator(`.nav-item:has-text("${NAME}")`).first().isVisible(),
  );
  check(
    "empty state explains abstention",
    await page.locator("text=Questions will abstain").isVisible(),
  );

  // --- upload a document ------------------------------------------------
  await page.setInputFiles('input[type="file"]', {
    name: "raft.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(RAFT),
  });
  const row = page.locator(".list-row", { hasText: "raft.md" });
  await row.waitFor({ timeout: 20000 });
  check("uploaded source appears", true);

  await row.locator(".pill-ready").waitFor({ timeout: 180000 });
  check(
    "ingestion completes via the worker",
    /chunk/.test((await row.textContent()) ?? ""),
    (await row.locator(".list-meta").textContent())?.trim(),
  );

  // --- ask ---------------------------------------------------------------
  await page.click('button:has-text("Start research")');
  await page.waitForSelector(".composer", { timeout: 20000 });
  check("research thread opens", true);

  await page.fill(".composer input", "How does Raft elect a leader?");
  await page.selectOption(".composer select", "2");
  await page.click('.btn-send:has-text("Send")');

  await page.locator(".bubble").first().waitFor({ timeout: 20000 });
  check("the question renders as a bubble", true);

  await page.waitForSelector(".tasks .task", { timeout: 90000 });
  check(
    "tasks stream into the plan panel",
    (await page.locator(".tasks .task").count()) > 0,
    `${await page.locator(".tasks .task").count()} tasks`,
  );

  await page.waitForSelector(".answer", { timeout: 240000 });
  const answer = (await page.locator(".answer").first().textContent()) ?? "";
  check(
    "grounded answer is rendered",
    answer.length > 80,
    `${answer.slice(0, 55).replace(/\s+/g, " ")}…`,
  );
  check("the model's duplicate Sources section is stripped", !/\bSources\b/.test(answer));
  check("markdown is rendered, not shown raw", !/\*/.test(answer));
  check(
    "citation markers render as references",
    (await page.locator(".answer .cite").count()) > 0,
  );

  // --- evidence ----------------------------------------------------------
  const cards = page.locator(".evidence");
  await cards.first().waitFor({ timeout: 20000 });
  check("evidence cards are shown", (await cards.count()) > 0, `${await cards.count()} cards`);
  const snippet = (await cards.first().locator(".evidence-snippet").textContent()) ?? "";
  check(
    "evidence card carries a passage snippet",
    snippet.length > 20,
    `${snippet.slice(0, 50)}…`,
  );
  check(
    "evidence resolves to the uploaded file",
    /raft\.md/.test((await page.locator(".evidence-grid").first().textContent()) ?? ""),
  );

  // --- follow-up and persistence ----------------------------------------
  await page.fill(".composer input", "And what makes a committed entry safe?");
  await page.click('.btn-send:has-text("Send")');
  await page.waitForFunction(
    () => document.querySelectorAll(".answer").length >= 2,
    null,
    { timeout: 240000 },
  );
  check("follow-up turn is appended", true);

  await page.reload({ waitUntil: "networkidle" });
  await page.locator(".answer").first().waitFor({ timeout: 20000 });
  check(
    "conversation persists across reload",
    (await page.locator(".bubble").count()) >= 2 &&
      (await page.locator(".answer").count()) >= 2,
  );
  check(
    "the open thread is highlighted in History",
    (await page.locator('.nav-item[data-active="true"]').count()) > 0,
  );

  // --- refusal -----------------------------------------------------------
  const before = await page.locator(".answer, .abstained").count();
  await page.fill(".composer input", "Compare Kafka and RabbitMQ delivery guarantees.");
  await page.click('.btn-send:has-text("Send")');
  await page.waitForFunction(
    (n) => document.querySelectorAll(".answer, .abstained").length > n,
    before,
    { timeout: 240000 },
  );
  const last = page.locator(".pipeline").last();
  const reply = (await last.textContent()) ?? "";
  check(
    "out-of-corpus question is refused, not answered",
    /outside|scope|focus|only|lacks?|contains? no|don.t|do not|cannot|can.t|could not|does not|unable|no (information|details|material)/i.test(
      reply,
    ),
    reply.replace(/\s+/g, " ").slice(0, 70),
  );
  check(
    "the refusal fabricates no evidence",
    (await last.locator(".evidence").count()) === 0,
  );

  await page.screenshot({ path: "e2e-thread.png", fullPage: true });

  // --- delete the conversation --------------------------------------------
  const openRow = page.locator('.nav-row:has(.nav-item[data-active="true"])');
  check(
    "the delete control is hidden until hover",
    (await openRow.locator(".nav-del").evaluate((e) => getComputedStyle(e).opacity)) ===
      "0",
  );
  await openRow.hover();
  await openRow.locator(".nav-del").click();
  await page.waitForSelector('button:has-text("Start research")', { timeout: 20000 });
  check(
    "deleting the open conversation returns to the collection",
    (await page.locator(".nav-row").count()) === 0,
  );

  // --- delete the collection ----------------------------------------------
  await page.click(`.nav-item:has-text("${NAME}")`);
  await page.waitForSelector('button:has-text("Delete collection")', { timeout: 20000 });
  await page.click('button:has-text("Delete collection")');
  await page
    .locator(`.nav-item:has-text("${NAME}")`)
    .waitFor({ state: "detached", timeout: 90000 });
  check("collection deletes from the UI", true);

  check("no uncaught browser errors", errors.length === 0, errors.slice(0, 2).join(" | "));
} catch (e) {
  check("run completed without throwing", false, String(e).split("\n")[0].slice(0, 160));
  await page.screenshot({ path: "e2e-failure.png", fullPage: true }).catch(() => {});
} finally {
  await browser.close();
}

const failed = results.filter((r) => !r.ok);
writeFileSync("e2e-results.json", JSON.stringify(results, null, 2));
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length === 0 ? 0 : 1);
