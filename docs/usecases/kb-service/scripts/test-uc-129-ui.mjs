// uc-129 a builder adds documents to a knowledge base by uploading them or picking them from Files, ui layer:
// docs/usecases/kb-service/add-documents-from-files.md. Signed in through platform-service as James; one PDF is put in
// Files first, then the console uploads a second and picks the first in one Add documents dialog.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { FILES_PORT, KB_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const kb = `http://127.0.0.1:${KB_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const JAMES = 'j.richardson@northfieldbank.com';
const TAG = Math.random().toString(36).slice(2, 6);
const NAME = `Branch documents ${TAG}`;
const PDFS = join(ROOT, 'services/kb-service/seed/pdfs');
const UPLOADED = 'branch-operations-manual.pdf';
const PICKED = `retail-product-sheet-${TAG}.pdf`;
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

/** Puts a PDF in Files as James through the three upload calls, the way the console's FileUpload does. */
async function putInFiles(H, name, bytes) {
  const digest = createHash('sha256').update(bytes).digest('hex');
  const ticket = (await (await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify({ name, size: bytes.length, mime: 'application/pdf', purpose: 'knowledge_source', digest }) })).json()).data;
  await fetch(new URL(ticket.uploadUrl, files), { method: 'PUT', headers: { ...H, ...ticket.headers }, body: bytes });
  return (await (await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: H })).json()).data.file;
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const H = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
      const existing = await putInFiles(H, PICKED, readFileSync(join(PDFS, 'retail-product-sheet.pdf')));
      check('a PDF is in Files before the console opens', existing?.scan?.status === 'clean', existing);

      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await page.goto(`${consoleUrl}/knowledge`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'New knowledge base' }).click({ timeout: 120_000 });
      const create = page.getByRole('dialog', { name: 'New knowledge base' });
      await create.locator('#kb-name').fill(NAME);
      await create.locator('#kb-owner').fill(JAMES);
      await create.locator('#kb-desc').fill('Branch procedures.');
      const made = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/knowledge-bases'), { timeout: 60_000 }));
      await create.getByTestId('kb-create').click();
      const kbId = (await (await made).json()).data.id;
      await page.waitForURL(`**/knowledge/${kbId}**`, { timeout: 60_000 });
      await page.getByRole('tab', { name: /^Sources/ }).waitFor({ timeout: 60_000 });
      const tabs = await page.getByRole('tab').allInnerTexts();
      check('the base offers no Documents tab', tabs.length > 0 && !tabs.some((t) => t.startsWith('Documents')), tabs);

      await page.goto(`${consoleUrl}/knowledge/${kbId}?tab=sources`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('kb-add-documents').first().click({ timeout: 120_000 });
      const dialog = page.getByRole('dialog', { name: 'Add documents' });
      const ticketed = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${files}/v1/files/uploads`, { timeout: 60_000 }));
      await dialog.locator('input[type="file"]').setInputFiles([{ name: UPLOADED, mimeType: 'application/pdf', buffer: readFileSync(join(PDFS, UPLOADED)) }]);
      const ticket = await ticketed;
      check('the upload goes to files-service first', ticket?.status() === 201, ticket?.status());
      const ready = await dialog.getByRole('button', { name: 'Add 1 document' }).waitFor({ timeout: 60_000 }).then(() => true, () => false);
      if (!ready) throw new Error(`upload not ready: ${await dialog.getByTestId('add-documents-upload').innerText()}`);

      // Files stores one copy of identical bytes per team, so the file may carry an earlier upload's name.
      await dialog.getByRole('button', { name: 'Pick from Files' }).click();
      await page.getByPlaceholder("Search your team's files by name…").fill(existing.name);
      await page.getByRole('option', { name: new RegExp(`^${existing.name.replace('.', '\\.')}`) }).first().click({ timeout: 30_000 });
      await page.keyboard.press('Escape');
      const added = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${kb}/v1/knowledge-bases/${kbId}/documents`, { timeout: 120_000 }));
      await dialog.getByRole('button', { name: 'Add 2 documents' }).click({ timeout: 30_000 });
      const res = await added;
      const body = res ? (await res.json()).data : undefined;
      const sent = res ? JSON.parse(res.request().postData() ?? '{}').fileIds : [];
      check('one call adds the upload and the picked file, and both index', res?.status() === 200 && sent?.length === 2 && sent.includes(existing.id) && body?.run?.counts?.upserted === 2, { status: res?.status(), sent, counts: body?.run?.counts });

      await page.reload({ waitUntil: 'domcontentloaded' });
      const row = await page.getByRole('row', { name: new RegExp(`${NAME} documents`) }).waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const src = (await (await fetch(`${kb}/v1/sources/${body?.sourceId}`, { headers: H })).json()).data;
      check('after a reload the documents source is listed, active, with two indexed items', row && src?.status === 'active' && src?.itemsIndexed === 2, { row, status: src?.status, itemsIndexed: src?.itemsIndexed });

      const refs = await Promise.all(sent.map(async (id) => (await (await fetch(`${files}/v1/files/${id}`, { headers: H })).json()).data?.references ?? []));
      check('Files keeps both files: each is referenced by the source', refs.every((r) => r.some((x) => x.type === "source" && x.id === body?.sourceId)), refs);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
