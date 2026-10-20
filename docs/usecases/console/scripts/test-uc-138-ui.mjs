// uc-138 knowledge, source and file pages follow what the caller may do with each record, ui layer:
// docs/usecases/console/record-pages-follow-record-flags.md (c-216). Platform sign-in; Priya is Operations' admin, Ravi
// its viewer. Each page's controls must match the record's own canEdit / canDelete as its service answers them.
import { createHash } from 'node:crypto';

import { FILES_PORT, KB_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const kb = `http://127.0.0.1:${KB_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = async (email) => ({ Authorization: `Bearer ${await tokenFor(email)}`, 'X-Team-Id': 'team_ops' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const PEOPLE = [
  ['Priya', 'p.shah@northfieldbank.com'],
  ['Ravi', 'r.menon@northfieldbank.com'],
];

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    const P = await as('p.shah@northfieldbank.com');
    // The first base and source the admin may change, by each one's own detail.
    const firstEditable = async (list, path) => {
      for (const row of list) if ((await json(await fetch(`${kb}/v1/${path}/${row.id}`, { headers: P }))).canEdit) return row;
      return undefined;
    };
    const base = await firstEditable((await json(await fetch(`${kb}/v1/knowledge-bases?page=1&pageSize=50`, { headers: P }))).data, 'knowledge-bases');
    const source = await firstEditable((await json(await fetch(`${kb}/v1/sources?page=1&pageSize=50`, { headers: P }))).data, 'sources');
    const body = Buffer.from(`uc-138 ${Date.now()}`);
    const ticket = await json(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...P, 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'uc-138.txt', size: body.length, mime: 'text/plain', purpose: 'knowledge_source', digest: createHash('sha256').update(body).digest('hex') }) }));
    await fetch(new URL(ticket.uploadUrl, files), { method: 'PUT', headers: { ...P, ...ticket.headers }, body });
    const file = (await json(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: P }))).file;
    if (!base || !source || !file) throw new Error(`setup: base ${!!base}, source ${!!source}, file ${!!file}`);

    const browser = await chromium.launch();
    const errors = [];
    const seen = {};
    try {
      for (const [who, email] of PEOPLE) {
        const H = await as(email);
        const flags = {
          base: await json(await fetch(`${kb}/v1/knowledge-bases/${base.id}`, { headers: H })),
          source: await json(await fetch(`${kb}/v1/sources/${source.id}`, { headers: H })),
          file: await json(await fetch(`${files}/v1/files/${file.id}`, { headers: H })),
        };
        const page = await signIn(browser, consoleUrl, email, errors);
        await page.goto(`${consoleUrl}/knowledge/${base.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('heading', { name: base.name }).first().waitFor({ timeout: 120_000 });
        const baseReadOnly = (await page.getByTestId('read-only').count()) > 0;
        await page.goto(`${consoleUrl}/integrations/sources/${source.id}?tab=settings`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('heading', { name: source.name }).first().waitFor({ timeout: 120_000 });
        const sourceReadOnly = (await page.getByTestId('read-only').count()) > 0;
        await page.goto(`${consoleUrl}/files?file=${file.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const del = page.getByTestId('file-delete');
        await del.waitFor({ timeout: 120_000 });
        const fileDeleteOff = await del.isDisabled();
        seen[who] = {
          base: { canEdit: flags.base.canEdit, readOnly: baseReadOnly },
          source: { canEdit: flags.source.canEdit, readOnly: sourceReadOnly },
          file: { canDelete: flags.file.canDelete, deleteOff: fileDeleteOff },
        };
      }
      const matches = (s) => s.base.readOnly === !s.base.canEdit && s.source.readOnly === !s.source.canEdit && s.file.deleteOff === !s.file.canDelete;
      check('each page follows the record’s own flags for each person', matches(seen.Priya) && matches(seen.Ravi), seen);
      check('the admin may change the base and the viewer may not, so the pages are tested both ways', seen.Priya.base.canEdit === true && seen.Ravi.base.canEdit === false, seen);
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
