// uc-673 a scanned file attached in chat is read with OCR and reaches the agent whole, ui layer:
// docs/usecases/agents-service/scanned-chat-attachment.md, story S4. Headless Chromium against a console whose chat
// calls agents-service on the scripted model, with files-service, documents-service and kb-service of the run's own.
// A banker attaches a page that is only a scan, asks about it, and the answer cites the scan's page.
import { fileURLToPath } from 'node:url';

import { AGENTS_PORT, check, chromium, finish, replyDone, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_ops' };
const armed = (p) => (p.catch(() => undefined), p);
// A page that is only a picture of "LATE PAYMENT FEE / The fee is 25 dollars.": no text layer.
const SCAN = fileURLToPath(new URL('../../../../packages/ops_ingest/tests/fixtures/scanned.pdf', import.meta.url));
const api = async (path, init = {}) => (await fetch(`${agents}${path}`, { ...init, headers: { ...TEAM, 'Content-Type': 'application/json', ...(init.headers ?? {}) } })).json();
const MESSAGES = /\/chat\/threads\/[^/]+\/messages$/;

await withUiStack(async (consoleUrl) => {
  const agent = (await api('/chat/agents')).data[0].id;
  const tid = (await api('/chat/threads', { method: 'POST', body: JSON.stringify({ agentId: agent, kbIds: [] }) })).data.id;
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.addInitScript(() => sessionStorage.setItem('ops-team', 'team_ops'));
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(`${consoleUrl}/chat/${tid}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const box = page.getByRole('textbox', { name: 'Message' });
    await box.waitFor({ timeout: 120_000 });

    await page.getByTestId('chat-attach').click();
    await page.getByRole('dialog').locator('input[type="file"]').setInputFiles(SCAN);
    await page.getByRole('dialog').locator('[data-phase="ready"]').first().waitFor({ timeout: 60_000 });
    await page.getByTestId('add-documents-submit').click();
    const ready = await page.getByTestId('chat-attached-file').first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
    await box.fill('What is the late payment fee?');
    const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && MESSAGES.test(r.url()), { timeout: 180_000 }));
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    await replyDone(await sent, 120_000);
    const marker = page.getByRole('button', { name: /^Citation \d+: scanned\.pdf/ }).last();
    const cited = await marker.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    if (cited) await marker.click();
    const location = cited ? await page.getByRole('dialog').getByTestId('citation-location').innerText().catch(() => '') : '';
    const last = (await api(`/chat/threads/${tid}`)).data.messages.at(-1);
    await page.screenshot({ path: process.env.OPS_UC_SHOT ?? '/tmp/uc-673-ui.png', fullPage: false });
    check('1 a scanned attachment is read by OCR and the answer cites its page', ready && cited && /scanned\.pdf · p\.1/.test(location), { ready, cited, location, reply: last?.content?.slice(0, 160), citations: last?.citations?.map((c) => `${c.title} p${c.page}`) });
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
