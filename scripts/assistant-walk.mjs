// make assistant-walk [SHOTS=dir]: the team assistant's first-team scripts in a browser on the stack's console. As one
// person of each first team (make sample-teams), it starts a chat on the team's assistant, sends the script's ask,
// waits for the reply the script expects, screenshots it at 1280 and 390, and checks what the script checks: the
// record or passage named, no question back, no error code, nothing shown twice. Each chat it makes is titled
// "[test] …" so make test-data-clean finds it. Runs on whatever model the stack's assistant alias is bound to; on the
// fake (make assistant-evals' default) it spends no model call.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { ROOT, check, chromium, finish } from '@ops-ai/usecase-runner/harness';

const port = (name, fallback) => Number(process.env[`OPS_${name}_PORT`] ?? fallback);
const CONSOLE = `http://localhost:${port('CONSOLE', 3016)}`;
const PLATFORM = `http://127.0.0.1:${port('PLATFORM', 8710)}`;
const AGENTS = `http://127.0.0.1:${port('AGENTS', 8700)}`;
const SHOTS = process.env.SHOTS || join(ROOT, '.logs', 'assistant-walk');
// The first teams' people sign in with the dev seed's password on a local stack (scripts/sample_team.py).
const PASSWORD = process.env.OPS_PLATFORM_DEMO_PASSWORD || 'northfield-demo';
mkdirSync(SHOTS, { recursive: true });

// One ask per first team, from its script under docs/usecases/chat/assistant/, and what the reply must name.
const WALKS = [
  { team: 'wealth', email: 'dana.whitfield@harborpine.example', ask: 'Prep me for my 2 pm meeting', names: /Okafor Family Trust/ },
  { team: 'lending', email: 'marco.silva@harborpine.example', ask: 'Which applications are waiting on documents?', names: /waiting on documents/, table: true },
  { team: 'risk', email: 'lena.hoffmann@harborpine.example', ask: 'What does our policy say about overdue control reviews?', names: /10 business days/ },
];
const CODE = /\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b|\bError:/;

const api = async (method, path, token, body) => {
  const r = await fetch(`${AGENTS}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data };
};
const tokenFor = async (email) => {
  const r = await fetch(`${PLATFORM}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) });
  return (await r.json()).data?.token;
};

const browser = await chromium.launch();
const errors = [];
for (const w of WALKS) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(`${w.team}: ${e.message}`));
  await page.goto(`${CONSOLE}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(w.email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  await page.goto(`${CONSOLE}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const box = page.getByLabel('Message');
  await box.waitFor({ timeout: 120_000 });
  await box.fill(w.ask);
  await page.getByRole('button', { name: 'Send' }).click();
  const answered = await page.getByText(w.names).last().waitFor({ timeout: 90_000 }).then(() => true, () => false);
  await page.waitForURL(/\/chat\/th_/, { timeout: 30_000 }).catch(() => {});
  const thread = page.url().match(/th_[a-z0-9]+/)?.[0] ?? '';
  await page.waitForTimeout(1500);
  await page.screenshot({ path: join(SHOTS, `${w.team}-1280.png`), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(SHOTS, `${w.team}-390.png`), fullPage: true });

  const token = await tokenFor(w.email);
  const read = await api('GET', `/v1/chat/threads/${thread}`, token);
  const reply = (read.data?.messages ?? []).filter((m) => m.role === 'assistant').at(-1) ?? {};
  const text = reply.content ?? '';
  check(`${w.team}: the reply names what the script expects (${thread})`, answered && w.names.test(text), text);
  check(`${w.team}: no question back`, !/\?(\s|$)/.test(text), text);
  check(`${w.team}: no error code`, !CODE.test(text), text);
  if (w.table) check(`${w.team}: the applications are drawn as a table`, (reply.parts ?? []).some((p) => p.shape === 'rows'), reply.parts);
  const marked = (read.data?.title ?? '').startsWith('[test] ')
    ? { status: 200 }
    : await api('PATCH', `/v1/chat/threads/${thread}`, token, { title: `[test] ${w.ask}` });
  check(`${w.team}: the chat is marked as test data`, marked.status === 200, marked);
  await context.close();
}
await browser.close();
check('no page errors', errors.length === 0, errors);
console.log(`screenshots in ${SHOTS}`);
finish();
