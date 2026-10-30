// uc-091 a banker narrows the agent for a thread within its limits and attaches a file, ui layer:
// docs/usecases/console/chat-overrides-within-limits.md. Headless Chromium against a console whose chat calls the agents
// service on the scripted model. The settings panel offers only what the agent's limits allow; a switched-off tool is
// not offered to the model; every turn records the settings it ran on; an attached PDF is cited by its page.
import { fileURLToPath } from 'node:url';

import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_ops' };
const armed = (p) => (p.catch(() => undefined), p);
const NAME = `Overrides Desk ${Math.random().toString(36).slice(2, 6)}`;
const PDF = fileURLToPath(new URL('../../../../services/kb-service/seed/pdfs/fee-schedule-v2.pdf', import.meta.url));
const ADDED = 'Answer in two sentences.';
const raw = (path, init = {}) => fetch(`${agents}${path}`, { ...init, headers: { ...TEAM, 'Content-Type': 'application/json', ...(init.headers ?? {}) } });
const api = async (path, init = {}) => (await raw(path, init)).json();
const MESSAGES = /\/chat\/threads\/[^/]+\/messages$/;

await withUiStack(async (consoleUrl) => {
  // A published agent whose limits allow a temperature range, added instructions and switching lookup_account off.
  const created = (await api('/v1/agents', { method: 'POST', body: JSON.stringify({ name: NAME, role: 'Answers account questions' }) })).data;
  const model = (await api(`/v1/agents/${created.id}`)).data.model ?? '';
  const limits = { allowedModels: [model], defaultModel: model, temperature: { min: 0, max: 1, default: 0.3 }, callersMayAddInstructions: true, switchableToolIds: ['lookup_account'], allowedKnowledgeBaseIds: [] };
  const saved = await raw(`/v1/agents/${created.id}`, { method: 'PATCH', body: JSON.stringify({ toolIds: ['lookup_account'], limits, note: 'limits' }) });
  if (!saved.ok) throw new Error(`setup: limits answered ${saved.status}: ${await saved.text()}`);
  const published = await raw(`/v1/agents/${created.id}/publish-requests`, { method: 'POST', body: JSON.stringify({ version: (await saved.json()).data.version, note: 'first' }) });
  if (!published.ok) throw new Error(`setup: publish answered ${published.status}: ${await published.text()}`);
  const tid = (await api('/chat/threads', { method: 'POST', body: JSON.stringify({ agentId: created.id, kbIds: [] }) })).data.id;
  const thread = async () => (await api(`/chat/threads/${tid}`)).data;

  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    // The dev console works in team_platform until a team is picked; this script's rows are in team_ops.
    await page.addInitScript(() => sessionStorage.setItem('ops-team', 'team_ops'));
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(`${consoleUrl}/chat/${tid}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const box = page.getByRole('textbox', { name: 'Message' });
    await box.waitFor({ timeout: 120_000 });
    const send = async (text) => {
      await box.fill(text);
      const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && MESSAGES.test(r.url()), { timeout: 120_000 }));
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      const res = await sent;
      await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
      await page.getByRole('button', { name: 'Regenerate' }).last().waitFor({ timeout: 60_000 }).catch(() => undefined);
    };
    const lookups = () => page.getByTestId('chat-tool-call').filter({ hasText: 'Lookup account' }).count();

    // Control: with nothing narrowed, the agent calls its lookup tool.
    await send('Look up CHQ-2219');
    const before = await lookups();

    // The panel offers only what the limits allow: no model picker for one model, a temperature range, added
    // instructions, and the one switchable tool.
    await page.getByRole('button', { name: 'Thread settings' }).click();
    const sheet = page.getByTestId('thread-settings');
    await sheet.getByRole('switch', { name: 'lookup_account' }).waitFor({ timeout: 30_000 });
    const offered = {
      model: await sheet.getByRole('combobox', { name: 'Model' }).count(),
      // The slider role is on its thumb; the label belongs to the field.
      temperature: await sheet.getByRole('slider').count(),
      instructions: await sheet.getByLabel('Add instructions').count(),
    };
    check('the settings panel offers only what the agent allows', offered.model === 0 && offered.temperature === 1 && offered.instructions === 1, offered);

    await sheet.getByRole('switch', { name: 'lookup_account' }).click();
    await sheet.getByLabel('Add instructions').fill(ADDED);
    const patched = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && /\/settings$/.test(r.url()), { timeout: 30_000 }));
    await sheet.getByRole('button', { name: 'Save' }).click();
    const patchStatus = (await patched)?.status();
    await sheet.waitFor({ state: 'hidden', timeout: 15_000 }).catch(() => undefined);
    // The saved toast sits over the composer's Send button until it goes.
    await page.getByText('Thread settings saved').waitFor({ state: 'hidden', timeout: 15_000 }).catch(() => undefined);

    await send('Look up CHQ-2219 again');
    const after = (await lookups()) - before;
    const reply = (await thread()).messages.filter((m) => m.role === 'assistant').at(-1);
    check('a tool switched off for the thread is not offered, and the turn records the settings it ran on', before === 1 && patchStatus === 200 && after === 0 && reply?.settings?.toolsOff?.includes('lookup_account') && reply?.settings?.addedInstructions?.[0] === ADDED, { before, patchStatus, after, settings: reply?.settings });

    // A value outside the limits is refused naming the field; the panel never offers it.
    const refused = await raw(`/chat/threads/${tid}/settings`, { method: 'PATCH', body: JSON.stringify({ temperature: 1.5 }) });
    const refusal = await refused.json();
    check('a value outside the limits is refused with the field it breaks', refused.status === 422 && refusal.error?.details?.field === 'overrides.thread.temperature', { status: refused.status, error: refusal.error });

    // An attached PDF: parsed at upload, cited by its page.
    const uploads = [];
    page.on('response', (r) => r.url().includes('/chat/attachments') && uploads.push(`${r.request().method()} ${r.status()}`));
    await page.locator('#chat-attach').setInputFiles(PDF);
    const ready = await page.getByTestId('chat-attach-items').locator('[data-phase="ready"]').waitFor({ timeout: 30_000 }).then(() => true, () => false);
    const chip = ready ? 'ready' : await page.getByTestId('chat-attach-items').innerHTML().catch(() => 'no chip');
    await send('What does a replacement debit card cost?');
    const marker = page.getByRole('button', { name: /^Citation 1: fee-schedule-v2\.pdf/ }).last();
    const cited = await marker.waitFor({ timeout: 30_000 }).then(() => true, () => false);
    if (cited) await marker.click();
    const location = cited ? await page.getByRole('dialog').getByTestId('citation-location').innerText().catch(() => '') : '';
    const last = (await thread()).messages.slice(-2).map((m) => ({ role: m.role, content: m.content.slice(0, 120), attachments: m.attachments, citations: m.citations?.map((c) => `${c.title} p${c.page}`) }));
    check('an attached PDF is read and the answer cites it by its page', cited && /Card fees · p\.3/.test(location), { cited, location, last, uploads, chip: String(chip).slice(0, 400) });

    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
