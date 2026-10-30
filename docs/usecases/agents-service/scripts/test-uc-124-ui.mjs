// uc-124 a workflow turns an uploaded invoice into fields a person can check, ui layer:
// docs/usecases/agents-service/extract-from-file.md. James's invoice workflow reads three uploaded invoices; each run's
// console page shows where it ended and its Extract step's sheet shows every field with its confidence and citation.
// Sam raises the extraction floor in Govern › Policies and the next run of the same invoice goes to review. Platform
// sign-in, documents-service and the fake model with this use case's rules; no real model is called.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { FILES_PORT, ROOT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, as, readRunPage, readStepSheet, saveAndPublish, setPolicy, settled, start } from '../../lib/workflow_ui.mjs';

const SAM = 's.adeyemi@harborpine.example';
const files = `http://127.0.0.1:${FILES_PORT}`;
const ID = `uc124_invoices_${Math.random().toString(36).slice(2, 6)}`;
const node = (id, type, parameters = {}) => ({ id, type, typeVersion: 1, parameters });
const end = (id, outcome) => node(id, 'ops.flow.end', { outcome });
const DEFINITION = {
  schemaVersion: 2,
  id: ID,
  name: `Invoice intake ${ID.slice(-4)}`,
  nodes: [
    node('start', 'ops.trigger.request', { inputSchema: { type: 'object', properties: { fileId: { type: 'string', format: 'file' } } } }),
    node('extract', 'ops.ai.extract', {
      file: '$.input.fileId',
      fields: [
        { key: 'invoice_no', type: 'text', required: true },
        { key: 'amount', type: 'money', required: true },
        { key: 'due_date', type: 'date', required: true },
      ],
    }),
    end('ok', 'ok'),
    end('review', 'review'),
    end('unreadable', 'unreadable'),
    end('failed', 'error'),
  ],
  connections: [
    ['start', 'payload', 'extract'],
    ['extract', 'ok', 'ok'],
    ['extract', 'review', 'review'],
    ['extract', 'unreadable', 'unreadable'],
    ['extract', 'error', 'failed'],
  ].map(([f, p, t]) => ({ from: { node: f, port: p }, to: { node: t, port: 'in' } })),
};

/** The invoices as the api layer draws them, with reportlab: a text invoice, one whose answer quotes a missing line, a scan. */
function invoices() {
  const dir = mkdtempSync(join(tmpdir(), 'uc124-'));
  const script = `
import sys
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas
def pdf(path, pages):
    c = canvas.Canvas(path, pagesize=LETTER)
    for lines in pages:
        if not lines:
            c.rect(72, 400, 300, 200, fill=1)
        for i, line in enumerate(lines):
            c.drawString(72, 720 - 18 * i, line)
        c.showPage()
    c.save()
d = sys.argv[1]
pdf(d + "/invoice.pdf", [["Invoice INV-2219", "Harbor & Pine Supplies"], ["Amount due: $1,234.50", "Due 2026-11-30"]])
pdf(d + "/invented.pdf", [["Invoice INV-7777", "Harbor & Pine Supplies"], ["Amount due: $1,234.50", "Due 30 Nov 2026"]])
pdf(d + "/scan.pdf", [[]])
`;
  execFileSync('uv', ['run', '--quiet', '--project', ROOT, 'python', '-c', script, dir]);
  return Object.fromEntries(['invoice', 'invented', 'scan'].map((n) => [n, readFileSync(join(dir, `${n}.pdf`))]));
}

/** Uploads a PDF to Files as the person, the way the console's upload does, and returns its file id. */
async function upload(headers, name, bytes) {
  const ticket = (await (await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers, body: JSON.stringify({ name, size: bytes.length, mime: 'application/pdf', purpose: 'case_attachment' }) })).json()).data;
  await fetch(`${files}/v1/files/uploads/${ticket.fileId}/content`, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/pdf' }, body: bytes });
  const done = (await (await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers })).json()).data;
  return done.file.id;
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = await as(JAMES);
    const made = await saveAndPublish(J, DEFINITION);
    if (!made.live) throw new Error(`setup: the invoice workflow did not go live: ${made.saved.status} ${JSON.stringify(made.saved.data).slice(0, 300)}`);
    const pdfs = invoices();
    const ids = {};
    for (const [name, bytes] of Object.entries(pdfs)) ids[name] = await upload(J, `${name}.pdf`, bytes);
    const runOf = async (fileId) => {
      const runId = await start(J, ID, { fileId }, { mode: 'live' });
      await settled(J, runId);
      return runId;
    };

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);

      const first = await runOf(ids.invoice);
      const okPage = await readRunPage(page, consoleUrl, first);
      const read = await readStepSheet(page, 'extract');
      const fields = read.output?.fields ?? {};
      check(
        '1 a text invoice ends OK, and its Extract sheet shows every field with a confidence and a page citation',
        okPage.outcome === 'ok' && fields.amount?.value === 1234.5 && typeof fields.amount?.confidence === 'number' && fields.invoice_no?.citation?.page === 1 && fields.invoice_no?.citation?.quote === 'Invoice INV-2219',
        { outcome: okPage.outcome, port: read.port, fields },
      );

      const second = await runOf(ids.invented);
      const reviewPage = await readRunPage(page, consoleUrl, second);
      const doubted = await readStepSheet(page, 'extract');
      check(
        '2 an answer quoting a line that is not on its page ends at Review, with that field scored 0',
        reviewPage.outcome === 'review' && JSON.stringify(doubted.output?.needsReview) === JSON.stringify(['invoice_no']) && doubted.output?.fields?.invoice_no?.confidence === 0,
        { outcome: reviewPage.outcome, needsReview: doubted.output?.needsReview, invoiceNo: doubted.output?.fields?.invoice_no },
      );

      const sam = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
      const raised = await setPolicy(sam, consoleUrl, 'extractionFloor', '0.95');
      const third = await runOf(ids.invoice);
      const floorPage = await readRunPage(page, consoleUrl, third);
      const floored = await readStepSheet(page, 'extract');
      check(
        '4 Sam sets a 95% floor in Policies, and the same invoice now ends at Review with its amount to check',
        raised === 200 && floorPage.outcome === 'review' && floored.output?.floor === 0.95 && (floored.output?.needsReview ?? []).includes('amount'),
        { policy: raised, outcome: floorPage.outcome, floor: floored.output?.floor, needsReview: floored.output?.needsReview },
      );
      await setPolicy(sam, consoleUrl, 'extractionFloor', '0.8');

      const fourth = await runOf(ids.scan);
      const scanPage = await readRunPage(page, consoleUrl, fourth);
      check('5 a scan with no text ends at Unreadable', scanPage.outcome === 'unreadable', { outcome: scanPage.outcome, status: scanPage.status });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, fakeModelRules: 'services/agents-service/tests/fixtures/invoice-extraction-fake-openai' },
);

finish();
