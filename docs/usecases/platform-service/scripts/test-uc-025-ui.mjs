// uc-025 audit, ui layer: docs/usecases/platform-service/audit-log.md. A console signed in through platform-service
// (dev seed: Priya Shah admin, James Richardson builder, both on team_ops). Priya invites a new address, the newcomer
// accepts, and the audit log, read from platform-service, names both people and counts them. Each step is checked alone.
import { PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const TAG = Math.random().toString(36).slice(2, 7);
const NEWCOMER = `audited.${TAG}@harborpine.example`;
const NAME = `Audited ${TAG.toUpperCase()}`;
const KEY = 'ops-platform-session';
const stored = (page) => page.evaluate((k) => JSON.parse(localStorage.getItem(k) ?? 'null'), KEY);

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    return undefined;
  }
}

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const priya = await signIn(browser, consoleUrl, 'p.shah@harborpine.example', errors);
      const token = (await stored(priya))?.token;
      const H = { Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
      // The invite and the join are set up through the API; uc-023 drives them through the console.
      const sent = await (await fetch(`${platform}/v1/settings/members/invite`, { method: 'POST', headers: H, body: JSON.stringify({ emails: [NEWCOMER], role: 'viewer' }) })).json();
      const link = sent.data.invites[0].token;
      await fetch(`${platform}/v1/invites/${link}/accept`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: NAME }) });

      // 1. The audit log names Priya on the invite and the newcomer on the join, each with its summary.
      await step('1 the audit log names who invited and who joined', async () => {
        const read = priya.waitForResponse((r) => r.url().startsWith(`${platform}/v1/audit?`), { timeout: 60_000 });
        await priya.goto(`${consoleUrl}/logs/audit`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const res = await read;
        const invited = priya.getByRole('row', { name: new RegExp(`Invited ${NEWCOMER.replace(/\./g, '\\.')} as viewer`) });
        const joined = priya.getByRole('row', { name: new RegExp(`${NEWCOMER.replace(/\./g, '\\.')} accepted the invitation`) });
        await invited.waitFor({ timeout: 60_000 });
        const inv = await invited.innerText();
        const join = await joined.innerText();
        const exportShown = await priya.getByRole('button', { name: /^Export/ }).count();
        check('1 the audit log names who invited and who joined', res.status() === 200 && exportShown === 1 && inv.includes('Priya Shah') && inv.includes('Invited') && join.includes(NAME) && join.includes('Joined'), { inv: inv.replace(/\s+/g, ' '), join: join.replace(/\s+/g, ' ') });
      });

      // 2. Access changes is counted by the service and lists only member and key entries.
      await step('2 Access changes counts and lists member entries only', async () => {
        const tab = priya.getByRole('tab', { name: /Access changes · \d+/ }).or(priya.getByRole('button', { name: /Access changes · \d+/ })).first();
        const label = await tab.innerText();
        const n = Number(label.match(/· (\d+)/)?.[1] ?? 0);
        const read = priya.waitForResponse((r) => r.url().startsWith(`${platform}/v1/audit?`) && r.url().includes('view=access'), { timeout: 60_000 });
        await tab.click();
        const body = await (await read).json();
        const actions = new Set(body.data.data.map((e) => e.action.split('.')[0]));
        check('2 Access changes counts and lists member entries only', n >= 2 && body.data.viewCounts.access === n && [...actions].every((a) => a === 'member' || a === 'key'), { label, actions: [...actions] });
      });

      // 3. James, a builder, is told the log is for admins, and platform-service refuses him.
      await step('3 a builder is told only an admin reads the log', async () => {
        const james = await signIn(browser, consoleUrl, 'j.richardson@harborpine.example', errors);
        await james.goto(`${consoleUrl}/logs/audit`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const said = await james.getByTestId('audit-admin-only').waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const t = (await stored(james))?.token;
        const r = await fetch(`${platform}/v1/audit`, { headers: { Authorization: `Bearer ${t}`, 'X-Team-Id': 'team_ops' } });
        // An export of the log is offered to the admins who may read it, not to a person told they may not.
        const exportOffered = await james.getByRole('button', { name: /^Export/ }).count();
        check('3 a builder is told only an admin reads the log', said && r.status === 403 && exportOffered === 0, { said, status: r.status, exportOffered });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
