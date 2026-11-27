// uc-949 open a document beside the text read from it, ui layer: docs/usecases/kb-service/open-a-document-beside-the-text.md, story S6 (steps 7-8).
// Signed in as James on the demo stack: a pushed two-paragraph PDF opens beside its text; a paragraph lights its lines on the page and a line selects its paragraph.
import { KB_PORT, PLATFORM_PORT, check, chromium, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';

const kb = `http://127.0.0.1:${KB_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

// A one-page PDF in its text layer: a title and two paragraphs of two lines each, written by hand so no library is needed.
function pdf() {
  const lines = [
    ['F2', 18, 720, 'Claims intake review'],
    ['F1', 11, 690, 'The event queue went live in three regions on 14 October.'],
    ['F1', 11, 676, 'Photo uploads after storms no longer stall the adjusters.'],
    ['F1', 11, 640, 'Omar Haddad is on call for the Intake service.'],
    ['F1', 11, 626, 'Page him if the queue is more than fifteen minutes behind.'],
  ];
  const text = lines.map(([f, s, y, t]) => `BT /${f} ${s} Tf 72 ${y} Td (${t}) Tj ET`).join('\n');
  const objs = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>',
    `<< /Length ${text.length} >>\nstream\n${text}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>',
  ];
  let out = '%PDF-1.4\n';
  const at = [];
  objs.forEach((o, i) => { at.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${at.map((n) => `${String(n).padStart(10, '0')} 00000 n \n`).join('')}`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const H = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      const post = async (path, body) => (await (await fetch(`${kb}${path}`, { method: 'POST', headers: H, body: JSON.stringify(body) })).json()).data;
      const base = await post('/v1/knowledge-bases', { name: `Claims intake ${TAG}`, owner: JAMES });
      const src = await post('/v1/sources', { type: 'push', name: `Project files ${TAG}`, kbIds: [base.id] });
      const { item } = await post(`/v1/sources/${src.id}/items`, { name: 'review.pdf', content: pdf().toString('base64'), mime: 'application/pdf' });

      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await page.goto(`${consoleUrl}/data/knowledge/documents/${item.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const paragraphs = page.getByTestId('document-text').locator('[data-block]');
      await paragraphs.first().waitFor({ timeout: 120_000 });
      await page.getByTestId('viewer-page-1').waitFor({ timeout: 120_000 });
      const first = await paragraphs.first().getAttribute('data-block');
      await paragraphs.first().click();
      const lit = page.locator(`[data-box-key="${first}"][data-selected="true"]`);
      check('7 choosing a paragraph presses it and lights each of its lines on the page', (await paragraphs.first().getAttribute('aria-pressed')) === 'true' && (await lit.count()) >= 2, { block: first, lit: await lit.count() });

      const second = await paragraphs.nth(1).getAttribute('data-block');
      await page.locator(`[data-box-key="${second}"]`).first().click();
      check('8 choosing a line on the page presses its paragraph', (await paragraphs.nth(1).getAttribute('aria-pressed')) === 'true' && (await paragraphs.first().getAttribute('aria-pressed')) === 'false', { second });

      await shootBothWidths(page, 'knowledge', 'uc-949-document-view', async () => {
        await page.goto(`${consoleUrl}/data/knowledge/documents/${item.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await paragraphs.first().waitFor({ timeout: 120_000 });
        await page.getByTestId('viewer-page-1').locator('img').waitFor({ timeout: 120_000 });
        await paragraphs.first().click();
        await page.getByTestId('viewer-page-1').scrollIntoViewIfNeeded();
      });
      check('no page errors', errors.length === 0, errors);
      await context.close();
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
