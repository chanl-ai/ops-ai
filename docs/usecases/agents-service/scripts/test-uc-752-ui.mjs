// uc-752, ui layer: docs/usecases/agents-service/an-agent-answers-from-a-knowledge.md. A person asks an agent that holds
// knowledge and sees the answer with its citation, which opens on its source passage; the same question to an agent
// with no knowledge draws no citation. MODE=mock (default) is the scripted model; MODE=real needs APPROVED_REAL_CALLS.
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
const REAL = process.env.MODE === 'real';
const armed = (p) => (p.catch(() => undefined), p);
const QUESTION = 'What is the daily wire limit for a personal account?';

async function send(page, text) {
  await page.getByRole('textbox', { name: 'Message' }).fill(text);
  const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await sent;
  await page.getByRole('button', { name: 'Stop', exact: true }).waitFor({ state: 'hidden', timeout: 90_000 }).catch(() => undefined);
}

await withUiStack(async (consoleUrl) => {
  const post = async (path, body) => (await (await fetch(`${agents}${path}`, { method: 'POST', headers: TEAM, body: JSON.stringify(body) })).json()).data;
  const cited = await post('/chat/threads', { agentId: 'ag_fraud', kbIds: ['kb_people'] });
  const bare = await post('/v1/agents', { name: 'Plain helper', role: 'Answers without documents' });
  await post(`/v1/agents/${bare.id}/publish-requests`, { version: bare.version, note: 'uc-752' });
  const plain = await post('/chat/threads', { agentId: bare.id, kbIds: [] });
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.addInitScript(() => sessionStorage.setItem('ops-team', 'team_ops'));
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    // Non-vacuous: the agent with no knowledge answers the same question and draws no citation.
    await page.goto(`${consoleUrl}/chat/${plain.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });
    await send(page, QUESTION);
    await page.getByRole('log').getByText(/./).last().waitFor({ timeout: 60_000 }).catch(() => undefined);
    check('1 an agent with no knowledge draws no citation', (await page.getByRole('button', { name: /^Citation \d+: / }).count()) === 0);

    await page.goto(`${consoleUrl}/chat/${cited.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });
    await send(page, QUESTION);
    const marker = page.getByRole('button', { name: /^Citation 1: / });
    await marker.waitFor({ timeout: 60_000 }).catch(() => undefined);
    const log = page.getByRole('log');
    const text = await log.innerText().catch(() => '');
    const raw = text.match(/\[\^?1\]|#cite-/g);
    // Real mode loosens the wording only: the citation marker is drawn the same way.
    const worded = REAL ? /limit|wire/i.test(text) : /\$25,000/.test(text);
    check('2 the answer draws its [1] as a citation, not as text', worded && (await marker.count()) === 1 && !raw, { markers: await marker.count(), raw });
    await marker.click();
    const opened = await page.getByRole('dialog').getByText(/limit/i).first().waitFor({ timeout: 10_000 }).then(() => true, () => false);
    const location = opened ? await page.getByRole('dialog').getByTestId('citation-location').innerText().catch(() => '') : '';
    check('3 the citation opens on its source passage at its section', opened && location.startsWith('Wire Transfer Policy > 4.2 Daily limits'), { opened, location });
    check('4 the page raised no script error', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});
finish();
