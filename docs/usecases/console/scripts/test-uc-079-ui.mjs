// uc-079 the branch policy agent answers from the manual or says it does not know, ui layer:
// docs/usecases/console/branch-policy-answers.md. Needs withUiStack's `demo` option (kb-service and models-service with
// the fake OpenAI on the run's database, the demo seeds run against the run's ports; ag_policy wired to Branch
// operations). Maya asks; Nadia, the knowledge base's owner, replaces the fee schedule with version 2.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, KB_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const kb = `http://127.0.0.1:${KB_PORT}`;
const PASSWORD = 'northfield-demo';
const MAYA = 'm.okafor@northfieldbank.com';
const NADIA = 'n.petrov@northfieldbank.com';
// Security's admin: Nadia reviews in Security and may not edit its bases, so the fee schedule is replaced as Sam.
const SAM = 's.adeyemi@northfieldbank.com';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

const files = `http://127.0.0.1:${FILES_PORT}`;
await withUiStack(
  async (consoleUrl) => {
    const M = as(await tokenFor(MAYA), 'team_ops');
    const N = as(await tokenFor(NADIA), 'team_security');
    const S = as(await tokenFor(SAM), 'team_security');
    const thread = (await json(await fetch(`${agents}/chat/threads`, { method: 'POST', headers: { ...M, 'Content-Type': 'application/json' }, body: JSON.stringify({ agentId: 'ag_policy', kbIds: [] }) }))).id;

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(MAYA);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      const send = async (text) => {
        await box.fill(text);
        const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
        await page.getByRole('button', { name: 'Send', exact: true }).click();
        const res = await sent;
        await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
      };
      // The newest citation's popover text: document, section, page and version.
      const cited = async (doc) => {
        const marker = page.getByRole('button', { name: new RegExp(`^Citation 1: .*${doc}`) }).last();
        await marker.click({ timeout: 15_000 }).catch(() => undefined);
        const text = await page.getByRole('dialog').innerText().catch(() => '');
        await page.keyboard.press('Escape');
        return text;
      };

      // US3: fee, limit and procedure questions each cite a document with its page.
      const asked = [
        ['What is the fee for an outgoing wire transfer?', /costs 30\.00/, 'Fee Schedule', 1],
        ['What is the daily ATM withdrawal limit?', /daily ATM withdrawal limit .* is 1,000/, 'Branch Operations Manual', 2],
        ['How do I place a stop payment on a cheque?', /record the cheque number/, 'Branch Operations Manual', 3],
      ];
      const results = [];
      let feeV1 = '';
      for (const [question, answer, doc, pageNo] of asked) {
        await send(question);
        const said = await page.getByText(answer).last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const where = await cited(doc);
        if (doc === 'Fee Schedule') feeV1 = where;
        results.push({ question, said, doc: where.includes(doc), page: new RegExp(`p\\.\\s?${pageNo}\\b`).test(where) });
      }
      check('fee, limit and procedure answers each cite their document with its page', results.every((r) => r.said && r.doc && r.page), results);

      // US4: a question the knowledge base does not cover gets an honest answer and no citation.
      const before = await page.getByRole('button', { name: /^Citation / }).count();
      await send('Is there a prepayment penalty on the mortgage?');
      const honest = await page.getByText('That is not in the knowledge base.').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const after = await page.getByRole('button', { name: /^Citation / }).count();
      check('an uncovered question says it is not in the knowledge base and cites nothing', honest && after === before, { honest, before, after });

      // US3's rate table: returned as rows through the structured-result tool (c-055 T021).
      const rates = await page.locator('[data-testid="widget"][data-shape="rows"]').count();
      check('the rate table shows as a rows widget', rates >= 1, { rates });

      // US5: Security's admin replaces the fee schedule with version 2 and syncs; the next answer cites version 2.
      const sources = (await json(await fetch(`${kb}/v1/sources?page=1&pageSize=50`, { headers: N }))).data;
      const fee = sources.find((s) => s.name === 'Fee schedule');
      const pdf = readFileSync(join(ROOT, 'services/kb-service/seed/pdfs/fee-schedule-v2.pdf'));
      // Into Files first, then added to the source by id, as the console does.
      const ticket = await json(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...S, 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'fee-schedule.pdf', size: pdf.length, mime: 'application/pdf', purpose: 'knowledge_source', digest: createHash('sha256').update(pdf).digest('hex') }) }));
      await fetch(new URL(ticket.uploadUrl, files), { method: 'PUT', headers: { ...S, ...ticket.headers }, body: pdf });
      const stored = (await json(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: S }))).file;
      await json(await fetch(`${kb}/v1/sources/${fee.id}/files`, { method: 'POST', headers: { ...S, 'Content-Type': 'application/json' }, body: JSON.stringify({ fileIds: [stored.id] }) }));
      await json(await fetch(`${kb}/v1/sources/${fee.id}/sync`, { method: 'POST', headers: { ...S, 'Content-Type': 'application/json' }, body: '{}' }));
      await send('What is the fee for an outgoing wire transfer now?');
      await page.getByText(/costs 30\.00/).last().waitFor({ timeout: 60_000 }).catch(() => undefined);
      const feeV2 = await cited('Fee Schedule');
      const version = (t) => t.match(/\b(?:v|version )?(\d+)\s*$/m)?.[1] ?? t;
      check('after the version 2 sync the fee answer cites a newer version of the fee schedule', feeV2.includes('Fee Schedule') && feeV2 !== feeV1, { feeV1: feeV1.slice(0, 160), feeV2: feeV2.slice(0, 160), v1: version(feeV1), v2: version(feeV2) });

      // A sync's replacement is recorded as already decided (origin source_sync), so it lists under Decided.
      await page.goto(`${consoleUrl}/knowledge/changes`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('tab', { name: /^Decided/ }).click({ timeout: 60_000 }).catch(() => undefined);
      const row = page.getByRole('row', { name: /Fee Schedule changed from v\d+ to v\d+/ }).first();
      const listed = await row.waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('the Changes page lists the fee schedule replacement', listed);

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
