// uc-132 the agent shows every generic widget kind in a chat, ui layer: docs/usecases/console/agent-shows-every-widget-kind.md.
// The scripted model calls `present` with the JSON after "call present"; each kind's data is the gallery's first sample.
import { readFileSync } from 'node:fs';

import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const SAMPLES = JSON.parse(readFileSync(new URL('../../../../apps/console/src/lib/widgets/kind-samples.json', import.meta.url), 'utf8'));
const KINDS = Object.keys(SAMPLES);
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
// The first text a kind's sample shows: what the drawn widget must contain.
const shown = (data) => data.title ?? data.name ?? data.label ?? data.passage ?? data.events?.[0]?.title ?? data.steps?.[0]?.label ?? data.items?.[0]?.label ?? data.columns?.[0]?.label ?? null;

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor('j.richardson@northfieldbank.com'));
    const agent = await json(await fetch(`${agentsUrl}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Widget desk ${TAG}`, role: 'Shows answers as widgets' }) }));
    await json(await fetch(`${agentsUrl}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: agent.version ?? 1, note: 'uc-132' }) }));
    const thread = (await json(await fetch(`${agentsUrl}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: agent.id, kbIds: [] }) }))).id;
    // A turn whose stream breaks is recorded with its kind rather than ending the run, so one bad kind names itself.
    const say = async (args) => {
      try {
        const r = await fetch(`${agentsUrl}/chat/threads/${thread}/messages`, { method: 'POST', headers: { ...J, Accept: 'text/event-stream' }, body: JSON.stringify({ content: `call present ${JSON.stringify(args)}` }) });
        return { status: r.status, body: await r.text() };
      } catch (e) {
        return { status: `broke: ${e.message}`, body: '' };
      }
    };

    const statuses = {};
    for (const kind of KINDS) {
      const r = await say({ kind, data: SAMPLES[kind][0].data });
      statuses[kind] = r.status === 200 && !r.body.includes('"type":"error"') ? 200 : { status: r.status, error: r.body.match(/"message":"[^"]*"/)?.[0] };
    }
    check('2 one present call per kind, each turn answered', Object.values(statuses).every((s) => s === 200), statuses);

    const refused = await say({ kind: 'tracker', data: { steps: [{ label: 'Packed', state: 'shipped' }] } });
    // The refusal goes back to the model as the tool's error (the field it names is checked in the kernel's
    // test_widget_kinds); the person is shown no widget for it.
    check('3 data outside the kind\'s schema draws nothing', refused.status === 200 && !refused.body.includes('"type": "part"'), refused.body.slice(-300));

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.locator('[data-testid="widget"][data-shape="kind"]').first().waitFor({ timeout: 120_000 });
      const drawn = {};
      for (const kind of KINDS) {
        const w = page.locator(`[data-testid="widget"][data-shape="kind"][data-kind="${kind}"]`);
        const n = await w.count();
        const text = n ? await w.first().innerText() : '';
        const want = shown(SAMPLES[kind][0].data);
        drawn[kind] = n === 1 && (!want || text.includes(String(want))) ? 'ok' : { count: n, want, text: text.slice(0, 80) };
      }
      const total = await page.locator('[data-testid="widget"]').count();
      check('4 each of the 17 kinds is drawn once with its sample text, and nothing else is', Object.values(drawn).every((v) => v === 'ok') && total === KINDS.length, { drawn, total });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
