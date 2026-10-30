// uc-244 Extract on a file saves what was read, and deleting the file purges it, ui layer:
// docs/usecases/agents-service/a-file-is-extracted-and-purged.md. James opens an uploaded court order notice in
// Files and asks for it to be read as a Levy notice; the system extract workflow reads it and saves the read on the
// file, which its page then shows. He deletes the file from Files, and the purge workflow removes what was read.
// Platform sign-in, documents-service and the demo's fake model; no real model is called.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { FILES_PORT, ROOT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, agents, as, settled, until } from '../../lib/workflow_ui.mjs';

const files = `http://127.0.0.1:${FILES_PORT}`;
const NAME = `levy-notice-${Math.random().toString(36).slice(2, 6)}.pdf`;
// A comment after the PDF's end makes it its own file: the seeded levy_notice samples hold the same bytes.
const NOTICE = Buffer.concat([readFileSync(join(ROOT, 'services/agents-service/tests/fixtures/mailbox/levy_notice.pdf')), Buffer.from(`\n% ${NAME}\n`)]);

async function upload(headers, name, bytes) {
  const ticket = (await (await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers, body: JSON.stringify({ name, size: bytes.length, mime: 'application/pdf', purpose: 'case_attachment' }) })).json()).data;
  await fetch(`${files}/v1/files/uploads/${ticket.fileId}/content`, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/pdf' }, body: bytes });
  return (await (await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers })).json()).data.file.id;
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = await as(JAMES);
    const fileId = await upload(J, NAME, NOTICE);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      await page.goto(`${consoleUrl}/files/${fileId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('file-extract').click({ timeout: 120_000 });
      await page.getByTestId('extract-type').click();
      await page.getByRole('option', { name: 'Levy notice', exact: true }).click();
      await page.getByTestId('extract-submit').click();
      // The dialog waits for the run the request starts, then opens the file's fields on it.
      await page.waitForURL(/\/fields\?run=/, { timeout: 120_000 });
      const runId = new URL(page.url()).searchParams.get('run');
      const run = runId ? await settled(J, runId, { orWaiting: true }) : undefined;
      check('1 James asks for the file to be read as a Levy notice, and its run reads and saves it', run?.status === 'succeeded' && run?.outcome === 'saved', { runId, status: run?.status, outcome: run?.outcome });

      await page.goto(`${consoleUrl}/files/${fileId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const readAs = await page.getByTestId('read-as').first().innerText({ timeout: 60_000 }).catch(() => '');
      check('2 the file page says it was read as a Levy notice', /Levy notice/.test(readAs), readAs);

      // Delete it from Files, as a person removes a file; the purge workflow runs from the deletion's event.
      await page.goto(`${consoleUrl}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = page.getByRole('row').filter({ hasText: NAME }).first();
      await row.waitFor({ timeout: 60_000 });
      await row.getByRole('button', { name: 'Open menu' }).click();
      await page.getByRole('menuitem', { name: 'Delete' }).click();
      const dialog = page.getByTestId('delete-file-dialog');
      await dialog.waitFor({ timeout: 30_000 });
      const typed = dialog.getByTestId('delete-file-confirm-input');
      if (await typed.count()) await typed.fill(NAME);
      const deleted = page.waitForResponse((r) => ['POST', 'DELETE'].includes(r.request().method()) && /\/v1\/files/.test(r.url()), { timeout: 60_000 }).then((r) => r.status(), () => 0);
      await dialog.getByTestId('delete-file-confirm-btn').click();
      const status = await deleted;
      const purged = await until(async () => {
        const rows = (await (await fetch(`${agents}/v1/runs?workflowId=file_deleted_purge&pageSize=20`, { headers: J })).json()).data?.data ?? [];
        const done = rows.find((r) => ['succeeded', 'failed'].includes(r.status));
        return done;
      }, 120);
      check('3 deleting the file in Files starts the purge, which ends purged', status >= 200 && status < 300 && purged?.outcome === 'purged', { status, purge: purged && { status: purged.status, outcome: purged.outcome } });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
