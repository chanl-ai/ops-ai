// uc-398 A crafted PDF runs no script in the viewer, ui layer: docs/usecases/console/pdf-scripts-never-run.md (c-350).
// Platform sign-in as James (Builder of Operations). The PDF is built here so every script it carries is visible.
import { FILES_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const files = `http://127.0.0.1:${FILES_PORT}`;
const MARK = 'pdf-script-ran';
const PATCHED = [6, 2, 108];
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

// One page of text, with JavaScript on the document's open action, a link on the page and a form field's keystroke.
// Each script alerts, submits to a marker URL and logs the marker, so any one of them running is seen.
function craftedPdf() {
  const js = `app.alert('${MARK}'); console.println('${MARK}'); this.submitForm('http://127.0.0.1:9/${MARK}');`;
  const text = `BT /F1 24 Tf 72 700 Td (uc-398 crafted ${TAG}) Tj ET`;
  const objects = [
    `<< /Type /Catalog /Pages 2 0 R /OpenAction 5 0 R /Names << /JavaScript << /Names [(open) 5 0 R] >> >> /AcroForm << /Fields [7 0 R] >> >>`,
    `<< /Type /Pages /Kids [3 0 R] /Count 1 >>`,
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 8 0 R >> >> /Annots [6 0 R 7 0 R] >>`,
    `<< /Length ${text.length} >>\nstream\n${text}\nendstream`,
    `<< /Type /Action /S /JavaScript /JS (${js}) >>`,
    `<< /Type /Annot /Subtype /Link /Rect [72 690 400 730] /Border [0 0 0] /A 5 0 R >>`,
    `<< /Type /Annot /Subtype /Widget /FT /Tx /T (note) /Rect [72 600 300 630] /P 3 0 R /AA << /K 5 0 R /Fo 5 0 R >> >>`,
    `<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>`,
  ];
  let out = '%PDF-1.7\n';
  const offsets = objects.map((body, i) => {
    const at = out.length;
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
    return at;
  });
  const xref = out.length;
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`;
  out += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return new TextEncoder().encode(out);
}

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor('j.richardson@northfieldbank.com')}`, 'X-Team-Id': 'team_ops' };
    const body = craftedPdf();
    const name = `crafted-${TAG}.pdf`;
    const ticket = await data(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ name, size: body.length, mime: 'application/pdf', purpose: 'case_attachment' }) }));
    const put = await fetch(new URL(ticket.uploadUrl, files).toString(), { method: 'PUT', headers: { ...J, ...ticket.headers }, body });
    const file = (await data(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: J }))).file;
    check('1 the crafted PDF uploads', put.status === 204 && !!file?.id, { put: put.status, file: file?.id });

    const browser = await chromium.launch();
    const errors = [];
    const seen = { dialogs: [], requests: [], logs: [], worker: '' };
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      page.setDefaultTimeout(60_000);
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('dialog', (d) => {
        seen.dialogs.push(d.message());
        void d.dismiss();
      });
      page.on('request', (r) => r.url().includes(MARK) && seen.requests.push(r.url()));
      page.on('console', (m) => m.text().includes(MARK) && seen.logs.push(m.text()));
      page.on('response', async (r) => {
        if (/pdf\.worker/.test(r.url())) seen.worker = await r.text().catch(() => '');
      });
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await page.goto(`${consoleUrl}/files/${file.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const drawn = await page.getByTestId('viewer-page-1').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      // Scripts on open run as the document loads; the link and field scripts on a click and a focus where they sit.
      if (drawn) {
        const at = await page.getByTestId('viewer-page-1').boundingBox();
        await page.mouse.click(at.x + at.width * 0.3, at.y + at.height * 0.09);
        await page.mouse.click(at.x + at.width * 0.25, at.y + at.height * 0.22);
      }
      await page.waitForTimeout(3000);
      // Leaving the page in the app (not a full load, which skips React's cleanup) frees the document; that must not
      // throw either.
      await page.locator('[data-sidebar="sidebar"] a[href="/files"]').first().click();
      await page.waitForURL((u) => u.pathname === '/files', { timeout: 60_000 });
      await page.waitForTimeout(1500);
      check('2 the viewer draws the page, no script in it runs, and leaving it frees the document cleanly', drawn && !seen.dialogs.length && !seen.requests.length && !seen.logs.length && !errors.length, { drawn, ...seen, worker: undefined, errors: errors.slice(0, 3) });

      const version = (seen.worker.match(/pdfjsVersion\s*=\s*"(\d+)\.(\d+)\.(\d+)"/) ?? seen.worker.match(/"(\d+)\.(\d+)\.(\d+)"/))?.slice(1).map(Number);
      const patched = !!version && (version[0] - PATCHED[0] || version[1] - PATCHED[1] || version[2] - PATCHED[2]) >= 0;
      check('3 the worker the browser loaded is PDF.js 6.2.108 or later', patched, { version: version?.join('.') ?? null, workerBytes: seen.worker.length });
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
