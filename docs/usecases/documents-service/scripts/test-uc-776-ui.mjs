// uc-776 A read no model reply answered goes to a person, ui layer:
// docs/usecases/documents-service/a-read-no-model-reply-answered.md. The run's own stack with the fake model
// answering one invoice's extraction cut off at the output limit; Priya (admin of Operations) and Ravi (a viewer) sign
// in through platform sign-in. The task and the Files panel are walked at 1440 and 390 wide.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const files = `http://127.0.0.1:${FILES_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const ADMIN = 'p.shah@harborpine.example';
const MEMBER = 'r.menon@harborpine.example';
const CUT = 'INV-77201';
const SHOTS = evidenceDir('776', 'screens');
const RULES = join(evidenceDir('776', 'rules'));

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, seconds = 120) {
  for (let i = 0; i < seconds * 2; i++) {
    const got = await fn();
    if (got) return got;
    await sleep(500);
  }
  throw new Error('timed out');
}

/** The documents fixtures' rules with the cut invoice ahead of them: Detect finds a supplier invoice, and its extraction reply stops at the output limit every time, so the retry stops too. */
function rulesFolder() {
  mkdirSync(RULES, { recursive: true });
  const base = JSON.parse(readFileSync(join(ROOT, 'services/documents-service/tests/fixtures/fake-model/script.json'), 'utf8'));
  const marker = CUT.replace('-', '\\-');
  const ours = [
    { when: `^Document types:.*${marker}`, tool: 'final_result', arguments: { typeId: 'supplier_invoice', confidence: 0.95, reason: `${CUT} is printed` } },
    { when: `^Fields:.*${marker}`, tool: 'final_result', arguments: { invoice_no: { value: CUT, quote: CUT, page: 1 } }, finish: 'length' },
  ];
  writeFileSync(join(RULES, 'script.json'), JSON.stringify({ ...base, rules: [...ours, ...base.rules] }));
  return RULES;
}

/** A one-page PDF whose text layer holds the lines, with a real cross-reference table. */
function pdf(lines) {
  const text = lines.map((l, i) => `BT /F1 12 Tf 72 ${700 - 24 * i} Td (${l.replace(/[()\\]/g, '')}) Tj ET`).join('\n');
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${Buffer.byteLength(text)} >>\nstream\n${text}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  let out = '%PDF-1.4\n';
  const at = [];
  objects.forEach((o, i) => {
    at.push(Buffer.byteLength(out));
    out += `${i + 1} 0 obj\n${o}\nendobj\n`;
  });
  const xref = Buffer.byteLength(out);
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${at.map((n) => `${String(n).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out);
}

async function upload(J, name, body) {
  const ticket = await data(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ name, size: body.length, mime: 'application/pdf', purpose: 'case_attachment' }) }));
  const put = await fetch(new URL(ticket.uploadUrl, files).toString(), { method: 'PUT', headers: { ...J, ...ticket.headers }, body });
  if (put.status !== 204) throw new Error(`setup: upload of ${name} answered ${put.status}`);
  return (await data(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: J }))).file;
}

let current;
async function step(name, body) {
  try {
    await body();
  } catch (e) {
    if (current) await current.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => undefined);
    check(name, false, String(e).slice(0, 500));
  }
}

/** The screen as it is at 1440 and at 390 wide, with nothing scrolling sideways. */
async function shots(page, name) {
  mkdirSync(SHOTS, { recursive: true });
  const wide = {};
  for (const [width, height] of [[1440, 1000], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.waitForTimeout(500);
    await page.screenshot({ path: join(SHOTS, `${name}-${width}.png`), fullPage: true });
    wide[width] = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  return wide;
}

async function signIn(browser, consoleUrl, email) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.setDefaultTimeout(60_000);
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = { Authorization: `Bearer ${await tokenFor(ADMIN)}`, 'X-Team-Id': 'team_ops' };
    const cut = await upload(J, 'lakeshore-77201.pdf', pdf(['Lakeshore Freight Co', `Invoice ${CUT}`, 'Bill to: Northfield Bank Facilities', 'Invoice date: 10/14/2026   Due date: 11/13/2026', 'Total due: $1,940.00']));
    // The read the Files page asks for: Detect, which the fake model answers, then the extraction it cuts off.
    const asked = await data(await fetch(`${files}/v1/files/${cut.id}/read-requests`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json', 'Idempotency-Key': `uc776-${Date.now()}` }, body: '{}' }));
    const runId = await until(async () => (await data(await fetch(`${files}/v1/files/${cut.id}/read-requests/${asked.key}`, { headers: J }))).runId);
    await until(async () => ['waiting', 'succeeded', 'failed', 'cancelled'].includes((await data(await fetch(`${agents}/v1/runs/${runId}`, { headers: J }))).status));
    const task = await data(await fetch(`${agents}/reviews/${encodeURIComponent(runId)}`, { headers: J }));
    const browser = await chromium.launch();
    const errors = [];
    try {
      const admin = await signIn(browser, consoleUrl, ADMIN);
      admin.on('pageerror', (e) => errors.push(e.message));
      current = admin;

      await step('5 the Files panel gives the reason and the way to the task, and the Activity row says it waits', async () => {
        await admin.goto(`${consoleUrl}/data/files/${cut.id}/fields`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await admin.getByTestId('file-not-read').waitFor({ timeout: 120_000 });
        await admin.getByTestId('file-open-task').waitFor({ timeout: 60_000 });
        const said = (await admin.getByTestId('file-not-read-reason').innerText()).replace(/\s+/g, ' ');
        const wide = await shots(admin, 'files-panel-admin');
        const href = await admin.getByTestId('file-open-task').getAttribute('href');
        await admin.goto(`${consoleUrl}/data/files/${cut.id}/activity`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await admin.getByTestId('file-activity-standing').waitFor({ timeout: 60_000 });
        const standing = (await admin.getByTestId('file-activity-standing').innerText()).replace(/\s+/g, ' ');
        await shots(admin, 'activity-admin');
        check(
          '5 the Files panel gives the reason and the way to the task, and the Activity row says it waits',
          /stopped at its length limit, and the one retry stopped too/.test(said) && /typed in the task/.test(said) && !!href && href.includes('review=') && /waiting in Human Tasks/.test(standing) && Object.values(wide).every((x) => x <= 1),
          { said, href, standing, wide },
        );
      });

      await step('6 the task shows what is left to type and holds Confirm until every required field has a value', async () => {
        await admin.goto(`${consoleUrl}/govern/reviews?review=${encodeURIComponent(task.id)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await admin.getByTestId('read-not-read').waitFor({ timeout: 120_000 });
        const badge = (await admin.getByTestId('required-to-type').first().innerText()).replace(/\s+/g, ' ');
        const alert = (await admin.getByTestId('read-not-read').innerText()).replace(/\s+/g, ' ');
        const status = (await admin.getByTestId('read-status-0-invoice_no').innerText()).replace(/\s+/g, ' ');
        const held = (await admin.getByTestId('decide-approve').innerText()).replace(/\s+/g, ' ');
        const disabled = await admin.getByTestId('decide-approve').isDisabled();
        const wide = await shots(admin, 'task-admin');
        await admin.getByTestId('read-input-0-invoice_no').fill(CUT);
        await admin.getByTestId('read-input-0-vendor').fill('Lakeshore Freight Co');
        await admin.getByTestId('read-input-0-total').fill('1,940.00');
        for (const key of ['invoice_no', 'total']) {
          const confirm = admin.getByTestId(`read-confirm-0-${key}`);
          if (await confirm.count()) await confirm.click();
        }
        await admin.waitForTimeout(400);
        const left = await admin.getByTestId('required-to-type').count();
        const ready = (await admin.getByTestId('decide-approve').isDisabled()) === false;
        await shots(admin, 'task-admin-typed');
        check(
          '6 the task shows what is left to type and holds Confirm until every required field has a value',
          /\d+ required to type/.test(badge) && /stopped at its length limit, and the one retry stopped too/.test(alert) && /Key field|Required/.test(status) && /Not read/.test(status) && disabled && /type \d+ required field/.test(held) && left === 0 && ready && Object.values(wide).every((x) => x <= 1),
          { badge, alert: alert.slice(0, 200), status, held, disabled, left, ready, wide },
        );
      });

      await step('7 a person who may only view reads the reason and the task, and cannot type or decide', async () => {
        const member = await signIn(browser, consoleUrl, MEMBER);
        member.on('pageerror', (e) => errors.push(e.message));
        current = member;
        await member.goto(`${consoleUrl}/data/files/${cut.id}/fields`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await member.getByTestId('file-not-read').waitFor({ timeout: 120_000 });
        // The task is looked up after the reason shows, so the link is what says the panel is done.
        await member.getByTestId('file-open-task').waitFor({ timeout: 60_000 });
        const extractAgain = await member.getByTestId('file-extract-again').count();
        const wideFiles = await shots(member, 'files-panel-member');
        await member.goto(`${consoleUrl}/govern/reviews?review=${encodeURIComponent(task.id)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await member.getByTestId('read-not-read').waitFor({ timeout: 120_000 });
        const reason = (await member.getByTestId('read-not-read-reason').innerText()).replace(/\s+/g, ' ');
        const inputs = await member.locator('[data-testid^="read-input-"]').count();
        const decide = await member.locator('[data-testid^="decide-"]').count();
        const wideTask = await shots(member, 'task-member');
        check(
          '7 a person who may only view reads the reason and the task, and cannot type or decide',
          extractAgain === 0 && /stopped at its length limit/.test(reason) && inputs === 0 && decide === 0 && [...Object.values(wideFiles), ...Object.values(wideTask)].every((x) => x <= 1),
          { extractAgain, reason, inputs, decide, wideFiles, wideTask },
        );
        current = admin;
      });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true, fakeModelRules: rulesFolder() },
);
finish();
