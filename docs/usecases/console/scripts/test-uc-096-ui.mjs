// uc-096 knowledge bases work end to end from the console, ui layer: docs/usecases/console/knowledge-bases-end-to-end.md.
// Signed in through platform-service as James, every step clicked as a person would: create a base, add files and a
// page, watch them index (one fails with its reason), ask the playground a question and see a cited answer, retire the
// base. Each step is checked on its own, so one failing step still lets the later ones report.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, KB_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const kb = `http://127.0.0.1:${KB_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@northfieldbank.com';
const TAG = Math.random().toString(36).slice(2, 6);
const NAME = `Teller procedures ${TAG}`;
const PDFS = join(ROOT, 'services/kb-service/seed/pdfs');
// A one-page PDF with no text layer, as a scan is: it must fail with its reason, never index empty.
const SCAN = Buffer.from(
  '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n' +
    '3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n' +
    'xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000052 00000 n \n0000000101 00000 n \n' +
    'trailer<</Size 4/Root 1 0 R>>\nstartxref\n164\n%%EOF\n',
);
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 300));
    return undefined;
  }
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    let kbId;
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // 1. Create a base from the list; the person lands on it (T002).
      await step('1 James creates a knowledge base and lands on it', async () => {
        await page.goto(`${consoleUrl}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'New knowledge base' }).click({ timeout: 120_000 });
        const dialog = page.getByRole('dialog', { name: 'New knowledge base' });
        await dialog.locator('#kb-name').fill(NAME);
        await dialog.locator('#kb-owner').fill(JAMES);
        await dialog.locator('#kb-desc').fill('Teller procedures and limits.');
        const made = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/knowledge-bases'), { timeout: 60_000 }));
        await dialog.getByTestId('kb-create').click();
        const res = await made;
        kbId = res ? (await res.json()).data?.id : undefined;
        const landed = await page.waitForURL(`**/knowledge/${kbId}**`, { timeout: 60_000 }).then(() => true, () => false);
        const title = await page.getByRole('heading', { name: NAME }).first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
        check('1 James creates a knowledge base and lands on it', res?.status() === 201 && landed && title, { status: res?.status(), url: page.url(), title });
      });

      // 2. Add files from the base's Sources tab: a file source, two PDFs, synced on add (T003).
      await step('2 James adds two PDFs from the Sources tab and syncs them', async () => {
        await page.goto(`${consoleUrl}/knowledge/${kbId}?tab=sources`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'Add source' }).first().click({ timeout: 120_000 });
        const add = page.getByRole('dialog', { name: 'Add source' });
        await add.locator('#ns-type').click();
        await page.getByRole('option', { name: /File/ }).first().click();
        await add.locator('#ns-name').fill(`Teller PDFs ${TAG}`);
        await add.getByTestId('new-source-submit').click();
        const files = page.getByRole('dialog', { name: /^Add files to/ });
        await files.waitFor({ timeout: 60_000 });
        await files.locator('input[type="file"]').setInputFiles([
          { name: 'branch-operations-manual.pdf', mimeType: 'application/pdf', buffer: readFileSync(join(PDFS, 'branch-operations-manual.pdf')) },
          { name: 'scanned-notice.pdf', mimeType: 'application/pdf', buffer: SCAN },
        ]);
        await files.getByTestId('new-source-files-items').getByText('scanned-notice.pdf').waitFor({ timeout: 60_000 });
        // Sync refuses while any file is still uploading, as a person would see; wait until both are stored.
        const busy = files.getByTestId('new-source-files-items').getByText(/Preparing|Uploading/);
        for (let i = 0; i < 120 && (await busy.count()) > 0; i++) await page.waitForTimeout(500);
        const synced = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/sources\/[^/]+\/sync$/.test(r.url()), { timeout: 120_000 }));
        await files.getByTestId('new-source-sync').click();
        const res = await synced;
        const run = res ? (await res.json()).data : undefined;
        check('2 James adds two PDFs from the Sources tab and syncs them', res?.status() === 200 && run?.counts?.upserted === 1 && run?.counts?.failed === 1, { status: res?.status(), counts: run?.counts });
      });

      // 3. Watch ingestion on the base: the manual indexed, the scan failed with its reason; the list counts one document and
      // shows the base degraded by the failure (T005).
      await step('3 the base shows each document indexed or failed with its reason, and the list counts them', async () => {
        await page.goto(`${consoleUrl}/knowledge/${kbId}?tab=documents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const manual = page.getByRole('row', { name: /Branch Operations Manual/ });
        if (!(await manual.waitFor({ timeout: 60_000 }).then(() => true, () => false))) {
          throw new Error(`no manual row; rows: ${JSON.stringify(await page.getByRole('row').allInnerTexts())}`);
        }
        const indexed = await manual.getByText('Indexed').count();
        const failedRow = page.getByRole('row', { name: /scanned-notice/ });
        const reason = await failedRow.getByText(/no text layer/i).first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
        await page.goto(`${consoleUrl}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = page.getByRole('row', { name: new RegExp(NAME) });
        if (!(await row.waitFor({ timeout: 60_000 }).then(() => true, () => false))) {
          throw new Error(`no base row; rows: ${JSON.stringify(await page.getByRole('row').allInnerTexts())}`);
        }
        // Read the cells by column header, so the count checked is the Documents column, not another that holds 1.
        const heads = (await page.getByRole('columnheader').allInnerTexts()).map((h) => h.trim());
        const cells = (await row.getByRole('cell').allInnerTexts()).map((c) => c.trim());
        const documents = cells[heads.indexOf('Documents')];
        const health = cells[heads.indexOf('Health')];
        check('3 the base shows each document indexed or failed with its reason, and the list counts them', indexed === 1 && reason && documents === '1' && health === 'Degraded', { indexed, reason, heads, cells });
      });

      // 4. Add a page: a titled text written in the console, indexed like a file (T004).
      await step('4 James writes a page in the console and it indexes', async () => {
        await page.goto(`${consoleUrl}/knowledge/${kbId}?tab=documents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'Add page' }).click({ timeout: 60_000 });
        const dialog = page.getByRole('dialog', { name: 'Add a page' });
        await dialog.getByLabel('Title').fill('Cash drawer limits');
        await dialog.getByLabel('Text').fill('## Drawer limit\n\nA teller drawer holds at most 5,000 dollars in cash at any time.');
        const saved = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/knowledge-bases\/[^/]+\/pages$/.test(r.url()), { timeout: 60_000 }));
        await dialog.getByRole('button', { name: 'Add page' }).click();
        const res = await saved;
        const row = await page.getByRole('row', { name: /Cash drawer limits/ }).getByText('Indexed').waitFor({ timeout: 60_000 }).then(() => true, () => false);
        check('4 James writes a page in the console and it indexes', res?.status() === 201 && row, { status: res?.status(), row });
      });

      // 5. Test a question in the playground: a cited answer by page and section, and no control that is not built (T006).
      await step('5 the playground answers with a citation by page and section', async () => {
        await page.goto(`${consoleUrl}/knowledge/${kbId}?tab=playground`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const unbuilt = await page.getByText(/^(Hybrid|Semantic|Rerank|Compare two configurations)$/).count();
        await page.getByLabel('Question').fill('What is the daily ATM withdrawal limit?');
        const asked = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/query$/.test(r.url()), { timeout: 60_000 }));
        await page.keyboard.press('Enter');
        const res = await asked;
        const cited = await page.getByText(/Branch Operations Manual.*p\.\s?\d+/).first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
        check('5 the playground answers with a citation by page and section', res?.status() === 200 && cited && unbuilt === 0, { status: res?.status(), cited, unbuilt });
      });

      // 6. Retire a base an agent cites: the name must be typed, the dialog names the agent, the base leaves the list,
      // and kb-service no longer serves it (T007). An agent still naming it answering from its other bases is
      // services/kb-service/tests/test_retrieval.py.
      await step('6 James retires a base an agent cites by typing its name, and it leaves the list', async () => {
        const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
        const agent = (await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Teller desk ${TAG}`, role: 'Answers teller questions' }) })).json()).data;
        await fetch(`${agents}/v1/agents/${agent.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ collections: [kbId] }) });
        await page.goto(`${consoleUrl}/knowledge/${kbId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: /More|Actions/ }).first().click({ timeout: 60_000 });
        await page.getByRole('menuitem', { name: /Delete|Retire/ }).click();
        const confirm = page.getByRole('dialog').last();
        const names = await confirm.getByText(`Teller desk ${TAG}`).first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
        const button = confirm.getByRole('button', { name: /Delete|Retire/ }).last();
        const lockedBefore = await button.isDisabled();
        await confirm.getByRole('textbox').fill(NAME);
        const removed = armed(page.waitForResponse((r) => r.request().method() === 'DELETE' && r.url().includes(`/v1/knowledge-bases/${kbId}`), { timeout: 60_000 }));
        await button.click();
        const res = await removed;
        await page.waitForURL((u) => u.pathname === '/knowledge', { timeout: 60_000 }).catch(() => undefined);
        const listed = await page.getByRole('row', { name: new RegExp(NAME) }).count();
        const H = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
        const gone = (await fetch(`${kb}/v1/knowledge-bases/${kbId}`, { headers: H })).status;
        check(
          '6 James retires a base an agent cites by typing its name, and it leaves the list',
          names && lockedBefore && (res?.status() ?? 0) === 204 && gone === 404 && listed === 0,
          { names, lockedBefore, status: res?.status(), gone, listed },
        );
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
