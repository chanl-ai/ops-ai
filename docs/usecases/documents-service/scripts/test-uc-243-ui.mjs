// uc-243 Builders manage document types, versions, samples and test runs in the console, ui layer:
// docs/usecases/documents-service/builders-manage-document-types.md (c-243). The run's own stack with the documents
// fixtures' fake model; platform sign-in as James, a builder of Operations.
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { DOCUMENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const files = `http://127.0.0.1:${FILES_PORT}`;
const documents = `http://127.0.0.1:${DOCUMENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const TYPE = 'restraining_notice';
const FIXTURES = join(ROOT, 'services/documents-service/tests/fixtures/restraining');
const SAMPLE = 'TEST003.pdf';
const SHOTS = join(ROOT, '.codeloop/evidence/243/screens');
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

async function upload(J, name, body) {
  const ticket = await data(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ name, size: body.length, mime: 'application/pdf', purpose: 'case_attachment' }) }));
  const put = await fetch(new URL(ticket.uploadUrl, files).toString(), { method: 'PUT', headers: { ...J, ...ticket.headers }, body });
  if (put.status !== 204) throw new Error(`setup: upload of ${name} answered ${put.status}`);
  return (await data(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: J }))).file;
}

// The page a failed step leaves on screen is kept beside the run's other shots.
let current;
async function step(name, body) {
  try {
    await body();
  } catch (e) {
    if (current) await current.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => undefined);
    check(name, false, String(e).slice(0, 400));
  }
}

async function shots(page, name) {
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: join(SHOTS, `${name}-1280.png`), fullPage: true });
  await page.setViewportSize({ width: 400, height: 800 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(SHOTS, `${name}-400.png`), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
}

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
    const typeNow = async () => data(await fetch(`${documents}/v1/document-types/${TYPE}`, { headers: J }));
    const versionOf = async (n) => data(await fetch(`${documents}/v1/document-types/${TYPE}/versions/${n}`, { headers: J }));
    // Its own bytes (a comment after %%EOF, which readers ignore): files-service keeps one file per digest, and the
    // fixture itself is already one of the type's seeded samples.
    const bytes = Buffer.concat([readFileSync(join(FIXTURES, SAMPLE)), Buffer.from('\n% uc-243 sample\n')]);
    const notice = await upload(J, 'uc243-notice.pdf', bytes);
    const expected = JSON.parse(readFileSync(join(FIXTURES, 'expected.json'), 'utf8'))[SAMPLE].expected;
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      page.setDefaultTimeout(60_000);
      current = page;
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await step('1 the list shows the team types and New type, because the server says the builder may create', async () => {
        await page.goto(`${consoleUrl}/document-types`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByText('Restraining notice').first().waitFor({ timeout: 120_000 });
        const listed = await data(await fetch(`${documents}/v1/document-types`, { headers: J }));
        const newType = await page.getByTestId('new-document-type-button').count();
        await shots(page, 'list');
        check('1 the list shows the team types and New type, because the server says the builder may create', listed.canCreate === true && newType === 1, { canCreate: listed.canCreate, newType, types: listed.items.map((t) => t.id) });
      });

      await step("2 the type page loads with its own skeleton, not the record skeleton's rail", async () => {
        // Hold the type's request so the loading state is on screen long enough to see.
        await page.route(new RegExp(`/document-types/${TYPE}$`), async (route) => {
          await new Promise((r) => setTimeout(r, 2500));
          await route.continue();
        });
        await page.goto(`${consoleUrl}/document-types/${TYPE}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        // Watched until the fields show: the shell's own skeleton comes first, so only the type page's loading state,
        // under its "Document type" header, counts, and the record skeleton must never appear.
        let own = 0;
        let rail = 0;
        for (let i = 0; i < 600 && !(await page.getByTestId('fields-table').count()); i++) {
          rail = Math.max(rail, await page.getByTestId('record-skeleton').count());
          const header = await page.getByRole('heading', { name: 'Document type', exact: true }).count();
          if (header && (await page.getByTestId('page-skeleton').count())) own = 1;
          await page.waitForTimeout(100);
        }
        await page.unroute(new RegExp(`/document-types/${TYPE}$`));
        await page.getByTestId('fields-table').waitFor({ timeout: 60_000 });
        await shots(page, 'type');
        check("2 the type page loads with its own skeleton, not the record skeleton's rail", own === 1 && rail === 0, { pageSkeleton: own, recordSkeleton: rail });
      });

      await step('3 New version is prefilled from the shown version and saves n+1, leaving n as it was', async () => {
        const before = await typeNow();
        const n = before.latestVersion;
        const shown = await versionOf(n);
        await page.getByTestId('new-version-button').click();
        await page.getByTestId('field-editor').waitFor();
        const rows = await page.locator('[data-testid^="field-row-"]').count();
        await page.getByLabel('Field 1 review below').fill('0.9');
        await page.getByTestId('save-version').click();
        await page.getByTestId('version-picker').filter({ hasText: `v${n + 1}` }).waitFor({ timeout: 60_000 });
        const after = await typeNow();
        const added = await versionOf(n + 1);
        const kept = await versionOf(n);
        check(
          '3 New version is prefilled from the shown version and saves n+1, leaving n as it was',
          rows === shown.fields.length && after.latestVersion === n + 1 && Number(added.fields[0].reviewBelow) === 0.9 && JSON.stringify(kept.fields) === JSON.stringify(shown.fields),
          { rows, fields: shown.fields.length, latest: after.latestVersion, added: added.fields[0].reviewBelow, keptFirst: kept.fields[0].reviewBelow },
        );
      });

      await step('4 a sample is added from the team files with the value it should read', async () => {
        const type = await typeNow();
        const before = type.samples.length;
        const caseField = (await versionOf(type.latestVersion)).fields.find((f) => f.key === 'case_no');
        await page.getByTestId('samples-tab').click();
        await page.getByTestId('add-sample-button').click();
        await page.getByTestId('sample-file-picker').getByRole('button', { name: /Pick from Files/ }).click();
        await page.getByPlaceholder("Search your team's files by name…").fill(notice.name);
        await page.getByRole('option', { name: new RegExp(notice.name.replace('.', '\\.')) }).first().click({ timeout: 60_000 });
        if (await page.getByRole('listbox').count()) await page.keyboard.press('Escape');
        await page.getByLabel(caseField.label, { exact: true }).fill(String(expected.case_no));
        await page.getByTestId('add-sample-submit').click();
        await page.getByText(`Samples · ${before + 1}`).waitFor({ timeout: 60_000 });
        const after = await typeNow();
        const mine = after.samples.find((s) => s.fileId === notice.id);
        check('4 a sample is added from the team files with the value it should read', after.samples.length === before + 1 && mine?.expected?.case_no === expected.case_no, { before, after: after.samples.length, sample: mine });
      });

      await step('5 Run test shows the estimate before anything runs, then per-field results', async () => {
        const started = [];
        page.on('request', (r) => {
          if (r.method() === 'POST' && /\/test-runs$/.test(r.url())) started.push(Date.now());
        });
        await page.getByTestId('tests-tab').click();
        await page.getByTestId('run-test-button').first().click();
        await page.getByTestId('test-estimate').waitFor({ timeout: 60_000 });
        const estimate = (await page.getByTestId('test-estimate').innerText()).replace(/\s+/g, ' ');
        const beforeRun = started.length;
        await shots(page, 'estimate');
        await page.getByTestId('start-test').click();
        await page.getByTestId('test-result').waitFor({ timeout: 600_000 });
        const result = (await page.getByTestId('test-result').innerText()).replace(/\s+/g, ' ');
        await shots(page, 'result');
        check(
          '5 Run test shows the estimate before anything runs, then per-field results',
          beforeRun === 0 && started.length === 1 && /20 samples/.test(estimate) && /Accuracy/.test(result) && /By field/.test(result),
          { beforeRun, started: started.length, estimate: estimate.slice(0, 240), result: result.slice(0, 240) },
        );
      });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { demo: true, platform: true, fakeModelRules: 'services/documents-service/tests/fixtures/fake-model' },
);
finish();
