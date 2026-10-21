// uc-128 chat starts on the team's default agent, ui layer: docs/usecases/agents-service/team-default-agent.md.
// The scripted agents service with platform sign-in: James is a builder of team_ops, Priya its admin.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const PRIYA = 'p.shah@harborpine.example';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const armed = (p) => (p.catch(() => undefined), p);

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      // Step 1: a builder sees the setting but cannot change it, and the service refuses him.
      const james = await signIn(browser, consoleUrl, JAMES, errors);
      await james.goto(`${consoleUrl}/settings/general`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const select = james.getByTestId('default-agent-select');
      await select.waitFor({ timeout: 120_000 });
      const off = await select.isDisabled();
      const hint = await james.getByText('A team admin changes this.').isVisible().catch(() => false);
      const put = await fetch(`${agents}/v1/chat/default-agent`, { method: 'PUT', headers: as(await tokenFor(JAMES)), body: JSON.stringify({ agentId: 'ag_branch' }) });
      check('1 a builder cannot change the default: the control is off and his PUT is 403', off && hint && put.status === 403, { off, hint, status: put.status });

      // Step 2: the admin makes Branch Concierge the default from its row.
      const priya = await signIn(browser, consoleUrl, PRIYA, errors);
      await priya.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = priya.getByRole('row').filter({ hasText: 'Branch Concierge' }).first();
      await row.waitFor({ timeout: 120_000 });
      await row.getByRole('button', { name: 'Open menu' }).click();
      await priya.getByRole('menuitem', { name: 'Make default' }).click();
      const dialog = priya.getByRole('dialog');
      const title = await dialog.getByRole('heading').first().innerText({ timeout: 30_000 });
      const saved = armed(priya.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith('/chat/default-agent'), { timeout: 60_000 }));
      await dialog.getByRole('button', { name: 'Make default' }).click();
      const status = (await saved)?.status();
      const badge = await row.getByText('Default', { exact: true }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('2 Make default asks first, saves, and marks the row', /^Make Branch Concierge the default for .+\?$/.test(title) && status === 200 && badge, { title, status, badge });

      // Step 3: a new chat is on the default without choosing.
      await priya.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const picker = priya.getByRole('combobox', { name: 'Agent' });
      await picker.waitFor({ timeout: 120_000 });
      const chosen = await picker.innerText();
      check('3 New chat starts on Branch Concierge', chosen.includes('Branch Concierge'), chosen.slice(0, 120));

      // Step 4: start the chat, then hand it to Card Dispute Resolver with @.
      const box = priya.getByRole('textbox', { name: 'Message' });
      const created = armed(priya.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads$/.test(r.url()), { timeout: 120_000 }));
      await box.fill('Hello');
      await priya.getByRole('button', { name: 'Send', exact: true }).click();
      const thread = (await (await created)?.json())?.data;
      await priya.waitForURL(/\/chat\/th_/, { timeout: 60_000 });
      await priya.getByText('I could not find that.').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      await box.fill('@Card');
      await priya.getByTestId('mention-list').getByText('Card Dispute Resolver').click();
      const notice = priya.getByTestId('handover-notice');
      const noticeText = await notice.innerText({ timeout: 30_000 }).catch(() => '');
      check('4 @ hands the chat over, with Back', /talking to Card Dispute Resolver/.test(noticeText) && /Back to Branch Concierge/.test(noticeText), { thread: thread?.id, noticeText });

      // Step 5: the reply is credited to the specialist, and Back ends the handover.
      const sent = armed(priya.waitForResponse((r) => r.request().method() === 'POST' && /\/messages$/.test(r.url()), { timeout: 120_000 }));
      await box.fill('Can I dispute a charge?');
      await priya.getByRole('button', { name: 'Send', exact: true }).click();
      await Promise.race([(await sent)?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
      const credit = await priya.getByTestId('reply-agent').last().innerText({ timeout: 60_000 }).catch(() => '');
      await notice.getByRole('button', { name: 'Back to Branch Concierge' }).click();
      const gone = await notice.waitFor({ state: 'detached', timeout: 30_000 }).then(() => true, () => false);
      check('5 the reply names Card Dispute Resolver, and Back ends the handover', credit === 'Card Dispute Resolver' && gone, { credit, gone });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
