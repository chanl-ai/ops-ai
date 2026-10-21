// uc-075 a department's PDFs become a cited answer, through the console on kb-service, ui layer:
// docs/usecases/console/knowledge-from-uploaded-pdfs.md. The ui harness's kb-service and the scripted model; signed in
// through platform-service as James. He creates a knowledge base, adds a file source and uploads the branch manual PDF
// into it, syncs and watches it index, finds it by search, asks an agent granted only that base and opens the
// citation's page and document; a second version of the PDF shows on Changes.
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, KB_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

// A failing check leaves a screenshot beside the card's other evidence.
const EVIDENCE = join(ROOT, '.codeloop', 'evidence', '072');
mkdirSync(EVIDENCE, { recursive: true });

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const kb = `http://127.0.0.1:${KB_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const PASSWORD = 'northfield-demo';
const TAG = Math.random().toString(36).slice(2, 6);
const KB = `Lending policy ${TAG}`;
const PDFS = join(ROOT, 'services/kb-service/seed/pdfs');
const files = `http://127.0.0.1:${FILES_PORT}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      const unserved = [];
      page.on('pageerror', (e) => errors.push(e.message));
      // Every knowledge call goes to kb-service; one it does not serve is a gap, not noise.
      page.on('response', (r) => r.url().includes('/v1/') && r.status() === 404 && unserved.push(`${r.request().method()} ${new URL(r.url()).pathname}`));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // A knowledge base with its owner, then a file source that takes the PDF's bytes and syncs.
      await page.goto(`${consoleUrl}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'New knowledge base' }).first().click();
      await page.getByLabel('Name').fill(KB);
      const owner = await page.getByLabel('Owner').inputValue();
      const made = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/knowledge-bases'), { timeout: 60_000 }));
      await page.getByTestId('kb-create').click();
      const createdRes = await made;
      const sentOwner = createdRes ? JSON.parse(createdRes.request().postData() ?? '{}').owner : undefined;
      check('a new knowledge base is created on kb-service with its owner, the signed-in person', createdRes?.status() === 201 && owner === JAMES && sentOwner === JAMES, { status: createdRes?.status(), owner, sentOwner });
      await page.waitForURL(/\/knowledge\/[^/?]+/, { timeout: 60_000 });
      const kbId = new URL(page.url()).pathname.split('/')[2];

      await page.getByTestId('kb-add-source').click();
      await page.getByTestId('new-source-type').click();
      await page.getByRole('option', { name: 'File upload' }).click();
      await page.getByLabel('Name').fill(`Lending sheets ${TAG}`);
      await page.getByTestId('new-source-submit').click();
      const ticketed = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${files}/v1/files/uploads`, { timeout: 60_000 }));
      await page.locator('input#ns-files').setInputFiles(join(PDFS, 'branch-operations-manual.pdf'));
      const ticket = await ticketed;
      await page.getByTestId('new-source-files-items').locator('[data-phase="ready"]').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      const adding = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/sources\/[^/]+\/files$/.test(r.url()), { timeout: 60_000 }));
      await page.getByTestId('new-source-sync').click();
      const added = await adding;
      await page.waitForURL(/\/integrations\/sources\/[^/?]+\?tab=items/, { timeout: 60_000 }).catch(() => undefined);
      const sourceUrl = page.url();
      let indexed = false;
      // Each check waits for the page to render (its tabs) after a reload; reading at once would only see the skeleton.
      for (let i = 0; i < 20 && !indexed; i++) {
        await page.getByRole('tab', { name: /^Items/ }).waitFor({ timeout: 30_000 }).catch(() => undefined);
        indexed = await page.getByText('Indexed').first().waitFor({ timeout: 2_000 }).then(() => true, () => false);
        if (!indexed) {
          await page.waitForTimeout(3_000);
          await page.reload({ waitUntil: 'domcontentloaded' });
        }
      }
      if (!indexed) await page.screenshot({ path: join(EVIDENCE, 'uc-075-source.png'), fullPage: true });
      check('the PDF uploads to files-service, the source adds it by id, and it indexes after the sync', ticket?.status() === 201 && added?.status() === 200 && indexed, { upload: ticket?.status(), added: added?.status(), indexed, sourceUrl, items: indexed ? undefined : (await page.locator('main').innerText().catch(() => '')).slice(-400) });

      // The list finds it by search.
      await page.goto(`${consoleUrl}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByPlaceholder('Search knowledge bases…').fill(TAG);
      await page.waitForTimeout(1_500);
      const rows = await page.locator('tbody tr').filter({ hasText: KB }).count();
      check('searching the knowledge bases list finds it', rows === 1, { rows });

      // An agent granted only this base; the scripted model answers a limit question from what retrieval found, and the
      // citation is kb-service's passage from the PDF.
      const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      const agent = (await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Branch desk ${TAG}`, role: 'Answers from the branch manual' }) })).json()).data;
      const grantRes = await (await fetch(`${agents}/v1/agents/${agent.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ collections: [kbId] }) })).json();
      const granted = grantRes.data;
      if (!granted) throw new Error(`setup: grant the base: ${JSON.stringify(grantRes).slice(0, 400)}`);
      await fetch(`${agents}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: granted.version, note: 'uc-075' }) });
      const thread = (await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: agent.id, kbIds: [kbId] }) })).json()).data;
      await page.goto(`${consoleUrl}/chat/${thread.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      await box.fill('What is the daily ATM withdrawal limit?');
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      await page.getByRole('button', { name: /^Citation 1: / }).last().waitFor({ timeout: 90_000 }).catch(() => undefined);
      await page.getByRole('button', { name: /^Citation 1: / }).last().click({ timeout: 15_000 }).catch(() => undefined);
      const popover = await page.getByRole('dialog').innerText().catch(() => '');
      const citedPage = popover.match(/p\.\s?(\d+)/)?.[1];
      await page.getByRole('button', { name: /^Open (document|at p\.\d+)$/ }).click().catch(() => undefined);
      // The document opens on the cited page: its first passage there is marked and scrolled into view.
      const landed = page.getByTestId('cited-page-chunk').first();
      const shown = await landed.waitFor({ timeout: 30_000 }).then(() => true, () => false);
      const where = shown ? await landed.innerText() : '';
      const inView = shown && (await landed.evaluate((el) => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= window.innerHeight; }));
      const panel = await page.getByRole('dialog').last().innerText().catch(() => '');
      check(
        'the citation shows the PDF passage with page, section and version and opens the document on the cited page',
        /Branch Operations Manual/.test(popover) && !!citedPage && /·\s*v\d+/.test(popover) && /branch-operations-manual\.pdf/.test(panel) && new RegExp(`p\\. ${citedPage}\\b`).test(where) && /Cited page/.test(where) && inView,
        { popover: popover.slice(0, 240), citedPage, where: where.slice(0, 160), inView },
      );

      // A second version under the same file name, put in Files and added to the source by id, as the demo seed does.
      // Different bytes in James's team, so Files stores a new file under this name. Changes shows it.
      const sid = new URL(sourceUrl).pathname.split('/').pop();
      const H = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
      const v2bytes = readFileSync(join(PDFS, 'fee-schedule-v2.pdf'));
      const v2ticket = (await (await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'branch-operations-manual.pdf', size: v2bytes.length, mime: 'application/pdf', purpose: 'knowledge_source', digest: createHash('sha256').update(v2bytes).digest('hex') }) })).json()).data;
      await fetch(new URL(v2ticket.uploadUrl, files), { method: 'PUT', headers: { ...H, ...v2ticket.headers }, body: v2bytes });
      const v2file = (await (await fetch(`${files}/v1/files/uploads/${v2ticket.fileId}/complete`, { method: 'POST', headers: H })).json()).data.file;
      const v2 = await fetch(`${kb}/v1/sources/${sid}/files`, { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify({ fileIds: [v2file.id] }) });
      const synced = await fetch(`${kb}/v1/sources/${sid}/sync`, { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' }, body: '{}' });
      // A sync's replacement is recorded as already decided (origin source_sync), so it lists under Decided.
      await page.goto(`${consoleUrl}/knowledge/changes`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      let listed = false;
      for (let i = 0; i < 10 && !listed; i++) {
        await page.getByRole('tab', { name: /^Decided/ }).click({ timeout: 30_000 }).catch(() => undefined);
        // The change takes the new file's title (the second version is a different PDF under the same name).
        listed = await page.getByRole('row', { name: /changed from v1 to v2/ }).first().waitFor({ timeout: 5_000 }).then(() => true, () => false);
        if (!listed) {
          await page.waitForTimeout(3_000);
          await page.reload({ waitUntil: 'domcontentloaded' });
        }
      }
      if (!listed) await page.screenshot({ path: join(EVIDENCE, 'uc-075-changes.png'), fullPage: true });
      check('a second version of the file shows on the Changes page', v2.status === 200 && synced.ok && listed, { upload: v2.status, sync: synced.status, listed });

      check('no knowledge call answered 404', unserved.length === 0, unserved);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
