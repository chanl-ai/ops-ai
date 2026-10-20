// uc-142 Channels on real data, ui layer: docs/usecases/console/channels-real.md (c-242). Platform sign-in; James works
// in Operations. Every number on the page is compared with what agents-service's GET /v1/channels returns.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor('j.richardson@northfieldbank.com')}`, 'X-Team-Id': 'team_ops' };
    const all = await json(await fetch(`${agents}/v1/channels?page=1&pageSize=100`, { headers: J }));
    const email = await json(await fetch(`${agents}/v1/channels?page=1&pageSize=100&type=email`, { headers: J }));

    const browser = await chromium.launch();
    const errors = [];
    try {
      const signIn = async (width) => {
        const page = await (await browser.newContext({ viewport: { width, height: 1000 } })).newPage();
        page.setDefaultTimeout(60_000);
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
        await page.getByLabel('Password').fill('northfield-demo');
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        return page;
      };
      const page = await signIn(1440);

      await step('1 the hub shows six kinds, three coming soon, and lists the team’s channels from the records', async () => {
        await page.goto(`${consoleUrl}/channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('channel-gallery').waitFor();
        const cards = await page.locator('[data-testid^="gallery-"]:not([data-testid^="gallery-action"])').evaluateAll((els) => els.map((e) => e.innerText));
        const soon = cards.filter((t) => t.includes('Coming soon')).map((t) => t.split('\n')[0]);
        const rows = await page.locator('[data-testid^="channel-row-"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid').slice('channel-row-'.length)));
        const expected = all.data.slice(0, rows.length).map((c) => c.id);
        check('1 the hub shows six kinds, three coming soon, and lists the team’s channels from the records', cards.length === 6 && soon.join() === 'MCP,Slack,Teams' && rows.length > 0 && JSON.stringify(rows) === JSON.stringify(expected), { cards: cards.length, soon, rows, expected });
      });

      await step('2 each built kind’s tab dot is the health the server gives it', async () => {
        const dots = Object.fromEntries(await page.locator('[data-testid^="channel-tab-"]').evaluateAll((els) => els.map((e) => [e.getAttribute('data-testid').slice('channel-tab-'.length), e.getAttribute('data-health')])));
        // A kind with no channels has no health yet; the page shows it as not set up.
        const want = Object.fromEntries(all.kinds.map((k) => [k.type, k.built ? (k.health ?? 'idle') : 'soon']));
        check('2 each built kind’s tab dot is the health the server gives it', JSON.stringify(dots) === JSON.stringify(Object.fromEntries(Object.keys(dots).map((t) => [t, want[t]]))), { dots, want });
      });

      await step('3 the email landing counts its week and links Activity to each of its mailboxes', async () => {
        await page.getByTestId('channel-tab-email').click();
        const card = page.getByTestId('channel-activity-email');
        await card.waitFor();
        const count = Number((await card.innerText()).split('\n')[0].replace(/,/g, ''));
        const sum = email.data.reduce((n, c) => n + (c.activity7d ?? 0), 0);
        const href = new URL(await card.getByRole('link', { name: /View activity/ }).getAttribute('href'), consoleUrl);
        const sources = href.searchParams.getAll('source');
        check('3 the email landing counts its week and links Activity to each of its mailboxes', count === sum && href.pathname === '/activity' && JSON.stringify(sources) === JSON.stringify(email.data.map((c) => `channel:${c.id}`)), { count, sum, sources });
      });

      await step('4 the old Deployments address lands on Channels and says so', async () => {
        await page.goto(`${consoleUrl}/deployments`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.waitForURL(/\/channels\?from=deployments/);
        const said = await page.getByText('Deployments are now Channels').waitFor().then(() => 1, () => 0);
        const generic = await page.getByTestId('deployments-moved-link').getAttribute('href');
        // An old address that named an agent links to where that agent's versions are live.
        await page.goto(`${consoleUrl}/deployments?agent=ag_fraud`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.waitForURL(/agent=ag_fraud/);
        const named = page.getByTestId('deployments-moved-link');
        await named.getByText(/Wire Fraud Sentinel’s versions are live/).waitFor({ timeout: 30_000 });
        const namedHref = await named.getAttribute('href');
        check('4 the old Deployments address lands on Channels and says so, linking to where versions are live', said === 1 && generic === '/agents' && namedHref === '/agents/ag_fraud?tab=channels', { url: page.url(), said, generic, namedHref });
      });

      await step('5 Chat embed › Embed on a page opens the embed dialog with its agent picker', async () => {
        await page.goto(`${consoleUrl}/channels/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('widget-embed-open').click();
        const dialog = page.getByRole('dialog', { name: 'Embed on a page' });
        const picker = await dialog.getByTestId('widget-embed-agent').count();
        check('5 Chat embed › Embed on a page opens the embed dialog with its agent picker', picker === 1, { picker });
        await page.keyboard.press('Escape');
      });

      await step('7 an embed’s version changes in its row, the server keeps it, and the agent page shows where it is live', async () => {
        const made = await json(await fetch(`${agents}/v1/widget-deployments`, { method: 'POST', headers: { ...J, 'Content-Type': 'application/json' }, body: JSON.stringify({ name: `Version check ${Date.now() % 100000}`, agentId: 'ag_fraud', origins: ['https://intranet.bank.example'] }) }));
        await page.goto(`${consoleUrl}/channels/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = page.getByTestId(`channel-row-${made.id}`);
        await row.waitFor();
        const patched = page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/channels/${made.id}`));
        await row.getByRole('combobox', { name: /^Version/ }).click();
        await page.getByRole('option', { name: /^Latest/ }).click();
        const res = await patched;
        const after = (await json(await fetch(`${agents}/v1/channels?page=1&pageSize=100&type=chat`, { headers: J }))).data.find((c) => c.id === made.id);
        // Applied at once (200), or held for a review (202) when the team reviews what a channel serves.
        const kept = res.status() === 200 ? after?.serves?.version === 'latest' : res.status() === 202;
        await page.goto(`${consoleUrl}/agents/ag_fraud?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const live = await page.getByTestId(`live-channel-${made.id}`).waitFor().then(() => true, () => false);
        // As approved: View activity carries the server's count, the places filter by Status, and the trail names Agents once.
        const sources = ['agent:ag_fraud', ...(await json(await fetch(`${agents}/v1/agents/ag_fraud/live`, { headers: J }))).rows.filter((r) => r.where.kind === 'channel').map((r) => `channel:${r.where.id}`)];
        const counted = (await (await fetch(`${agents}/v1/activity?${new URLSearchParams([['page', '1'], ['pageSize', '1'], ...sources.map((x) => ['source', x])])}`, { headers: J })).json()).data.pagination.total;
        const activityText = await page.getByTestId('versions-live').getByRole('link', { name: /View activity/ }).innerText();
        const statusFilter = await page.getByRole('button', { name: 'Status' }).count();
        const trail = await page.locator('header').first().innerText();
        check('7 an embed’s version changes in its row, the server keeps it, and the agent page shows where it is live', kept && live, { status: res.status(), version: after?.serves?.version, live });
        check('7b the agent tab counts its activity as the server does, filters by Status, and names Agents once in the trail', activityText.includes(`· ${counted.toLocaleString('en-CA')}`) && statusFilter >= 1 && !/Agents\s*\/\s*Agents/.test(trail), { activityText, counted, statusFilter, trail: trail.slice(0, 80) });
      });

      await step('6 at 400 px the hub and the email page do not scroll sideways', async () => {
        const phone = await signIn(400);
        const widths = {};
        for (const path of ['/channels', '/channels/email']) {
          await phone.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await phone.getByTestId('page-title').first().waitFor();
          await phone.waitForTimeout(800);
          widths[path] = await phone.evaluate(() => document.documentElement.scrollWidth);
        }
        check('6 at 400 px the hub and the email page do not scroll sideways', Object.values(widths).every((w) => w <= 400), widths);
      });

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  // The seeded team mailboxes, as the shared stack has them, so the hub has channels to list.
  { platform: true, tools: { gateway: true }, agentsEnv: { OPS_MAILBOXES_SEED_FILE: 'seed/mailboxes.json' } },
);
finish();
