// uc-629 A file's page shows its preview or says why not, ui layer: docs/usecases/files-service/file-page-preview.md.
// Priya (admin) and Ravi (viewer) open a PDF, an image, a text file and a PDF whose stored bytes are gone, none of them
// read for text yet, at 1280 and 390. Screenshots go to OPS_USECASE_SHOTS when set. Platform sign-in; no model call.
import { readFileSync, readdirSync, statSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { FILES_PORT, ROOT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const RAVI = 'r.menon@harborpine.example';
const files = `http://127.0.0.1:${FILES_PORT}`;
const SHOTS = process.env.OPS_USECASE_SHOTS || evidenceDir('629', 'uc');
// Bytes of this run only: the same bytes as a file the team already holds complete as that file, under its name.
const RUN = Buffer.from(`\n% uc-629 ${Date.now()}\n`);
const own = (bytes) => Buffer.concat([bytes, RUN]);
const FILES = [
  { key: 'pdf', name: 'levy-notice.pdf', mime: 'application/pdf', purpose: 'knowledge_source', bytes: own(readFileSync(join(ROOT, 'services/documents-service/tests/fixtures/restraining/TEST012.pdf'))), shows: 'pages' },
  { key: 'image', name: 'channel-activity.png', mime: 'image/png', purpose: 'case_attachment', bytes: own(readFileSync(join(ROOT, 'docs/console/approved/channels/activity-400.png'))), shows: 'pages' },
  { key: 'text', name: 'branch-hours.txt', mime: 'text/plain', purpose: 'case_attachment', bytes: own(Buffer.from('Branches open 9 to 5 on weekdays.\n')), shows: 'download' },
  { key: 'gone', name: 'retail-product-sheet.pdf', mime: 'application/pdf', purpose: 'knowledge_source', bytes: own(Buffer.concat([readFileSync(join(ROOT, 'services/documents-service/tests/fixtures/restraining/TEST012.pdf')), Buffer.from('% gone\n')])), shows: 'missing', drop: true },
];

async function upload(headers, f) {
  const ticket = (await (await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers, body: JSON.stringify({ name: f.name, size: f.bytes.length, mime: f.mime, purpose: f.purpose }) })).json()).data;
  await fetch(`${files}/v1/files/uploads/${ticket.fileId}/content`, { method: 'PUT', headers: { ...headers, ...ticket.headers, 'Content-Type': f.mime }, body: f.bytes });
  return (await (await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers })).json()).data.file.id;
}

/** The stored object of a file, in the run's files directory: removed to leave a row whose bytes are gone. */
function dropBytes(fileId) {
  const walk = (dir) => readdirSync(dir).flatMap((n) => (statSync(join(dir, n)).isDirectory() ? walk(join(dir, n)) : n.startsWith(fileId) ? [join(dir, n)] : []));
  const found = readdirSync(tmpdir()).filter((d) => d.startsWith('usecase-files-')).flatMap((d) => walk(join(tmpdir(), d)));
  for (const f of found) unlinkSync(f);
  return found;
}

async function signIn(browser, consoleUrl, email, width) {
  const page = await (await browser.newContext({ viewport: { width, height: 900 } })).newPage();
  page.problems = [];
  page.on('pageerror', (e) => page.problems.push(`error ${e.message}`));
  // Next cancels its tab prefetches (`_rsc`) when the page changes; those aborts are not failures of the page.
  page.on('requestfailed', (r) => !(r.failure()?.errorText === 'net::ERR_ABORTED' && new URL(r.url()).searchParams.has('_rsc')) && page.problems.push(`failed ${r.url()} ${r.failure()?.errorText}`));
  page.on('response', (r) => r.status() === 404 && /documents\/layout/.test(r.url()) && page.problems.push(`404 ${r.url()}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    const P = await as(PRIYA);
    for (const f of FILES) f.id = await upload(P, f);
    const dropped = dropBytes(FILES.find((f) => f.drop).id);
    check('0 one PDF is left with its record but not its bytes, as on the shared stack', dropped.length >= 1 && dropped.every((d) => d.includes(FILES.find((f) => f.drop).id)), { dropped });
    const browser = await chromium.launch();
    try {
      for (const [who, email] of [['admin', PRIYA], ['viewer', RAVI]]) {
        for (const width of [1280, 390]) {
          const page = await signIn(browser, consoleUrl, email, width);
          for (const f of FILES) {
            const tag = `${who}-${f.key}-${width}`;
            page.problems.length = 0;
            await page.goto(`${consoleUrl}/files/${f.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            await page.getByText(f.name).first().waitFor({ timeout: 60_000 }).catch(async (e) => {
              await page.screenshot({ path: join(SHOTS, `failed-${tag}.png`) });
              throw new Error(`${String(e).split('\n')[0]} at ${page.url()}: ${(await page.locator('main').innerText().catch(() => '')).slice(0, 200)}`);
            });
            const settled = {
              pages: () => page.getByTestId('viewer-page-1').waitFor({ timeout: 60_000 }),
              download: () => page.getByText('Preview shows PDFs and images').waitFor({ timeout: 60_000 }),
              missing: () => page.getByText('missing from storage').waitFor({ timeout: 60_000 }),
            }[f.shows];
            const shown = await settled().then(() => true, () => false);
            await page.waitForTimeout(1500);
            const banner = await page.getByTestId('services-down').count();
            await page.screenshot({ path: join(SHOTS, `file-${tag}.png`), fullPage: true });
            const wide = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
            check(`${FILES.indexOf(f) + 1} ${tag}: ${f.shows === 'pages' ? 'its pages show' : f.shows === 'download' ? 'it says to download it' : 'the preview says its content is missing'}, with no outage banner, no failed request and no layout 404`, shown && banner === 0 && page.problems.length === 0 && !wide, { shown, banner, wide, problems: page.problems.slice(0, 3) });
          }
          await page.context().close();
        }
      }
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
