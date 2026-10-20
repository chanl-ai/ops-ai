// uc-112 a builder works the Files page on files-service, ui layer: docs/usecases/console/files-page-on-files-service.md.
// Signed in through platform-service. The used file gets its reference through files-service's public references
// route with a kb-service token (the dev key), the one caller granted files:edit.
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

import { FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const files = `http://127.0.0.1:${FILES_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const PASSWORD = 'northfield-demo';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const serviceToken = (tenant) =>
  execFileSync('uv', ['run', 'python', '-c', `from ops_identity import dev_service_signer, mint_service_token; print(mint_service_token(dev_service_signer(), service="kb", audience="files", tenant_id="${tenant}", scopes=["files:edit"], team_id="team_ops", ttl_s=600))`], { cwd: join(ROOT, 'services/files-service'), encoding: 'utf8' }).trim();

async function upload(J, name, text) {
  const body = new TextEncoder().encode(text);
  const ticket = await data(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ name, size: body.length, mime: 'text/plain', purpose: 'case_attachment' }) }));
  const url = new URL(ticket.uploadUrl, files).toString();
  const put = await fetch(url, { method: 'PUT', headers: { ...J, ...ticket.headers }, body });
  if (put.status !== 204) throw new Error(`setup: upload of ${name} answered ${put.status}`);
  return (await data(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: J }))).file;
}

await withUiStack(
  async (consoleUrl) => {
    const jToken = await tokenFor('j.richardson@northfieldbank.com');
    const J = { Authorization: `Bearer ${jToken}`, 'X-Team-Id': 'team_ops' };
    const tenant = JSON.parse(Buffer.from(jToken.split('.')[1], 'base64url').toString()).tenant_id;
    const used = await upload(J, `used-${TAG}.txt`, `used ${TAG}`);
    const spare = await upload(J, `spare-${TAG}.txt`, `spare ${TAG}`);
    const held = await upload(J, `held-${TAG}.txt`, `held ${TAG}`);
    const ref = await fetch(`${files}/v1/files/${used.id}/references`, { method: 'POST', headers: { Authorization: `Bearer ${serviceToken(tenant)}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'chat', refId: `msg_${TAG}`, name: `Chat message ${TAG}` }) });
    if (!ref.ok) throw new Error(`setup: the reference answered ${ref.status}: ${await ref.text()}`);

    const browser = await chromium.launch();
    try {
      const signIn = async (email) => {
        const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })).newPage();
        const errors = [];
        page.on('pageerror', (e) => errors.push(e.message));
        // A refused request (a 403 for settings the person may not read) shows as a console error, not a page error.
        page.on('console', (m) => m.type() === 'error' && errors.push(`${m.text()} ${m.location().url}`));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill(email);
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        return { page, errors };
      };
      const { page, errors } = await signIn('j.richardson@northfieldbank.com');
      const asked = [];
      page.on('request', (r) => r.url().startsWith(`${files}/v1/files?`) && asked.push(new URL(r.url()).searchParams));

      // Step 1: the list from files-service, its count, and no hold actions for a builder.
      await page.goto(`${consoleUrl}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByText(`used-${TAG}.txt`).first().waitFor({ timeout: 120_000 });
      const allTab = await page.getByText(/^All · \d+/).first().innerText();
      const served = await data(await fetch(`${files}/v1/files?page=1&pageSize=10`, { headers: J }));
      check('the list and its All count come from files-service', allTab.trim() === `All · ${served.viewCounts.all}` && served.viewCounts.all >= 3 && asked.length > 0, { allTab, all: served.viewCounts.all, asked: asked.map(String) });
      // files-service scopes the list to one team, so no Team column; the sheet below names it, not its id.
      check('the list draws no Team column on files-service', !(await page.getByRole('columnheader', { name: /^Team/ }).count()));
      check('a builder sees no legal hold action', (await page.getByRole('button', { name: /legal hold/i }).count()) === 0);

      // Step 2: search runs on the server.
      await page.getByPlaceholder('Search names, uploaders or digests…').fill(`spare-${TAG}`);
      await page.waitForTimeout(1200);
      const rows = page.locator('table tbody tr');
      check('a search is answered by files-service with that file only', asked.some((q) => q.get('search') === `spare-${TAG}`) && (await rows.count()) === 1, { rows: await rows.count() });
      await page.getByPlaceholder('Search names, uploaders or digests…').fill('');
      await page.waitForTimeout(1200);

      // Step 3: the used file's references and its delete reason.
      // The name opens the file's own page; the rest of the row opens the sheet.
      await page.getByRole('row', { name: new RegExp(`used-${TAG}`) }).getByText(/^\d+(\.\d+)? (B|KB|MB)$/).last().click();
      const sheet = page.getByTestId('file-sheet');
      await sheet.getByText(`Chat message ${TAG}`).waitFor({ timeout: 30_000 }).catch(() => undefined);
      const del = sheet.getByRole('button', { name: 'Delete' });
      const detailsText = await sheet.innerText();
      check('the sheet names the team and says the file was not scanned', /team\s*Operations/i.test(detailsText) && !detailsText.includes('team_ops') && /scan\s*Not scanned/i.test(detailsText) && !/scanning is off/.test(detailsText), detailsText.replace(/\s+/g, ' ').slice(0, 400));
      check('the sheet names the chat message that uses it and disables Delete', (await sheet.getByText(`Chat message ${TAG}`).count()) > 0 && (await del.isDisabled()), { disabled: await del.isDisabled().catch(() => null) });

      // Step 4: download through the service.
      const downloading = page.waitForEvent('download', { timeout: 30_000 }).catch(() => null);
      await sheet.getByRole('button', { name: 'Download' }).click();
      const dl = await downloading;
      const saved = dl ? await dl.path() : null;
      const bytes = saved ? (await import('node:fs')).readFileSync(saved, 'utf8') : '';
      check('Download fetches the bytes through files-service', bytes === `used ${TAG}`, { name: dl?.suggestedFilename(), bytes });

      // Step 5: an unused file deletes. It opens by its link, as cases and toasts open a file.
      await page.goto(`${consoleUrl}/files?file=${spare.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sheet.getByText(`spare-${TAG}.txt`).first().waitFor({ timeout: 60_000 });
      await sheet.getByRole('button', { name: 'Delete' }).click();
      await page.getByTestId('delete-file-confirm-btn').click({ timeout: 15_000 });
      await page.getByText(`spare-${TAG}.txt`).first().waitFor({ state: 'detached', timeout: 30_000 }).catch(() => undefined);
      const gone = await fetch(`${files}/v1/files/${spare.id}`, { headers: J });
      check('an unused file is deleted', gone.status === 404 && (await page.getByText(`spare-${TAG}.txt`).count()) === 0, gone.status);

      // Step 5b: Upload on the page takes a new file under a purpose the person chooses, and the list shows it.
      await page.goto(`${consoleUrl}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('files-upload').click();
      const up = page.getByRole('dialog');
      await up.getByTestId('add-documents-purpose').click();
      await page.getByRole('option', { name: 'Knowledge source' }).click();
      const offersPick = await up.getByText('Or pick from Files').count();
      // Unique content: an upload with the bytes of a stored file reuses that file instead of adding one.
      const named = `upload-${TAG}.txt`;
      await up.locator('input[type="file"]').first().setInputFiles({ name: named, mimeType: 'text/plain', buffer: Buffer.from(`uploaded on the Files page ${TAG}`) });
      // Add is enabled once the upload is stored and scanned.
      const add = up.getByTestId('add-documents-submit');
      for (let i = 0; i < 90 && !(await add.isEnabled()); i++) await page.waitForTimeout(1000);
      await add.click();
      const listed = await page.getByText(named).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const all = (await data(await fetch(`${files}/v1/files?page=1&pageSize=50`, { headers: J }))).data ?? [];
      const stored = all.filter((f) => f.name === named);
      check('Upload on Files takes a new file under the chosen purpose and lists it', listed && offersPick === 0 && stored[0]?.purpose === 'knowledge_source', { listed, offersPick, stored: stored.map((f) => [f.name, f.purpose]), newest: all.map((f) => f.name).slice(0, 3) });

      // Step 6: an admin of the team places a hold.
      const priya = await signIn('p.shah@northfieldbank.com');
      await priya.page.goto(`${consoleUrl}/files?file=${held.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const pSheet = priya.page.getByTestId('file-sheet');
      await pSheet.getByRole('button', { name: 'Legal hold' }).click({ timeout: 60_000 });
      const reason = priya.page.getByLabel('Matter or reason');
      await reason.fill(`LH-${TAG}`);
      // The dialog is one form: Enter in the reason places the hold, as the button does.
      await reason.press('Enter');
      await priya.page.getByText(/Under legal hold · 1/).first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      const detail = await data(await fetch(`${files}/v1/files/${held.id}`, { headers: J }));
      check('an admin places a legal hold and the view counts it', detail.legalHold?.reason === `LH-${TAG}` && (await priya.page.getByText(/Under legal hold · 1/).count()) > 0, detail.legalHold);

      // The storage section is for admins of the file's team, names the backend by what it is, and the footer fits a phone.
      const storage = await pSheet.getByRole('heading', { name: 'Storage' }).locator('xpath=ancestor::section[1]').innerText().catch(() => '');
      await priya.page.setViewportSize({ width: 400, height: 900 });
      const nav = await pSheet.getByTestId('detail-sheet-nav').boundingBox();
      await priya.page.setViewportSize({ width: 1440, height: 1000 });
      check('the storage section names the team admins and the local disk', /admins of this file’s team/.test(storage) && /backend\s*Local disk/i.test(storage) && !/Azure/.test(storage), storage.replace(/\s+/g, ' ').slice(0, 300));
      check('the sheet footer keeps prev and next inside a 400 px screen', !!nav && nav.x >= 0 && nav.x + nav.width <= 400, nav);

      check('no page or console errors', [...errors, ...priya.errors].length === 0, [...errors, ...priya.errors]);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
