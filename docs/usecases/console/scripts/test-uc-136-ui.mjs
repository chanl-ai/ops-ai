// uc-136 embedding the agent chat works end to end from the console, ui layer:
// docs/usecases/console/embed-agent-chat-from-console.md. Platform sign-in; James builds in Operations, Ravi is its
// viewer, Sam is an admin of Security only, so he edits there and not here. The Branch Concierge (ag_branch) is Operations' published agent.
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const AGENT = 'ag_branch';
const TAG = Math.random().toString(36).slice(2, 6);
const KEYISH = /ok_[A-Za-z0-9]|wk\.|api.?key|secret|getSsoToken|widget\/v1\.js/i;

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

async function create(page, dialog, name) {
  await dialog.getByLabel('Name').fill(name);
  const origins = dialog.getByLabel('Pages allowed to embed it');
  await origins.fill(`https://intranet-${TAG}.bank.example`);
  await origins.press('Enter');
  const made = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/widget-deployments'), { timeout: 60_000 });
  await dialog.getByTestId('widget-embed-create').click();
  const status = (await made).status();
  // The dialog takes the embed's name once it is created, so the snippet is found by its test id.
  const shown = page.getByRole('dialog').filter({ has: page.getByTestId('widget-snippet') });
  const pageCode = (await shown.getByTestId('widget-snippet').innerText({ timeout: 30_000 })).trim();
  const server = (await shown.getByTestId('widget-snippet-server').innerText()).trim();
  const id = /deployment: "([^"]+)"/.exec(pageCode)?.[1];
  return { status, pageCode, server, id, steps: await shown.getByTestId('widget-snippet-steps').count() };
}

await withUiStack(
  async (consoleUrl, stack) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const ravi = await signIn(browser, consoleUrl, 'r.menon@harborpine.example', errors);
      await ravi.goto(`${consoleUrl}/agents/${AGENT}?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await ravi.getByText('Embeds on other sites').waitFor({ timeout: 120_000 });
      const raviButton = await ravi.getByTestId('widget-embed-open').count();
      await ravi.goto(`${consoleUrl}/agents/${AGENT}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const raviWhy = await ravi.getByTestId('read-only-why').innerText({ timeout: 120_000 });
      const sam = await signIn(browser, consoleUrl, 's.adeyemi@harborpine.example', errors);
      await sam.goto(`${consoleUrl}/agents/${AGENT}?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByText('Embeds on other sites').waitFor({ timeout: 120_000 });
      const samButton = await sam.getByTestId('widget-embed-open').count();
      await sam.goto(`${consoleUrl}/agents/${AGENT}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const samWhy = await sam.getByTestId('read-only-why').innerText({ timeout: 120_000 });
      check(
        '3 whoever may not change the agent is offered no Embed on a page, and the notice names the owning team and never the reader',
        raviButton === 0 && samButton === 0 && !raviWhy.includes('Ravi Menon') && /Operations/.test(samWhy) && !samWhy.includes('Sam Adeyemi'),
        { raviButton, samButton, raviWhy, samWhy },
      );
      const james = await signIn(browser, consoleUrl, 'j.richardson@harborpine.example', errors);
      await james.goto(`${consoleUrl}/agents/${AGENT}?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('widget-embed-open').click({ timeout: 120_000 });
      const one = await create(james, james.getByRole('dialog', { name: 'Embed on a page' }), `Intranet ${TAG}`);
      check(
        '1 the snippet is the mint-key flow: the server mints a session, the page loads the embed loader with the deployment and tenant',
        one.status === 201 && !!one.id && one.pageCode.includes(`${stack.embedUrl ?? agents}/embed/v1.js`) && /OpsChat\.init/.test(one.pageCode) && /tenant: "[^"<]+"/.test(one.pageCode) && one.server.includes(`/v1/widget-deployments/${one.id}/sessions`) && one.server.includes('$OPS_WIDGET_KEY') && !KEYISH.test(one.pageCode) && one.steps === 1,
        one,
      );
      await james.keyboard.press('Escape');

      // The origin is the page's as the browser sends it; a bare host is refused in the dialog and nothing is sent.
      await james.getByTestId('widget-embed-open').click({ timeout: 60_000 });
      const bad = james.getByRole('dialog', { name: 'Embed on a page' });
      await bad.getByLabel('Name').fill(`Bare host ${TAG}`);
      const originBox = bad.getByLabel('Pages allowed to embed it');
      await originBox.fill('intranet.bank.example');
      await originBox.press('Enter');
      // Refused as it is typed: it stays in the box with the reason, and no tag is added.
      const refusedOnEntry = await bad.getByTestId('widget-origins-refused').waitFor({ timeout: 10_000 }).then(() => true, () => false);
      const tags = await bad.getByRole('button', { name: /^Remove / }).count();
      let posted = 0;
      const count = (r) => r.method() === 'POST' && r.url().endsWith('/v1/widget-deployments') && posted++;
      james.on('request', count);
      await bad.getByTestId('widget-embed-create').click();
      const said = await bad.getByText(/Use the page's origin|Add the page origin/).waitFor({ timeout: 10_000 }).then(() => true, () => false);
      james.off('request', count);
      check('1b a page origin without its scheme is refused as it is typed and nothing is sent', refusedOnEntry && tags === 0 && said && posted === 0, { refusedOnEntry, tags, said, posted });
      await james.keyboard.press('Escape');

      // Mint keys says what the bank's server calls, with what, and when each key ends.
      await james.locator(`[data-testid="widget-embed-row"][data-id="${one.id}"]`).getByTestId('widget-keys-open').click({ timeout: 60_000 });
      const keys = james.getByRole('dialog', { name: /^Mint keys for/ });
      const facts = (await keys.getByTestId('widget-key-facts').innerText({ timeout: 30_000 })).trim();
      await keys.getByLabel('Name').fill(`Server ${TAG}`);
      await keys.getByTestId('widget-key-days').click();
      await james.getByRole('option', { name: '30 days' }).click();
      const minted = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/widget-deployments/${one.id}/keys`), { timeout: 60_000 });
      await keys.getByTestId('widget-key-create').click();
      const keyRes = await minted;
      const expires = (await keys.getByTestId('widget-key-expires').first().innerText({ timeout: 30_000 })).trim();
      const in30 = new Date(Date.now() + 30 * 86_400_000).toLocaleDateString('en-US', { dateStyle: 'medium' });
      check(
        '1c Mint keys names the session endpoint, its fields and origins, and when the new key ends',
        facts.includes(`/v1/widget-deployments/${one.id}/sessions`) && /Bearer/.test(facts) && /email/.test(facts) && /origin/.test(facts) && facts.includes(`https://intranet-${TAG}.bank.example`) && keyRes.status() === 201 && expires === in30,
        { facts, status: keyRes.status(), expires, in30 },
      );
      await james.keyboard.press('Escape');

      // Channels › Chat embed opens the same dialog with an agent picker (Deployments folded into Channels, c-242).
      await james.goto(`${consoleUrl}/channels/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('widget-embed-open').click({ timeout: 120_000 });
      const dialog = james.getByRole('dialog', { name: 'Embed on a page' });
      await dialog.getByTestId('widget-embed-agent').click({ timeout: 30_000 });
      await james.getByRole('option', { name: 'Branch Concierge' }).click({ timeout: 30_000 });
      const two = await create(james, dialog, `Channels ${TAG}`);
      check('2 Channels › Chat embed › Embed on a page picks an agent, creates the embed and shows the same snippet', two.status === 201 && !!two.id && two.id !== one.id && two.pageCode.includes('/embed/v1.js'), two);

      // 4. Preview as a person: the embed's real chat, loaded from the embed app in a frame on the console's origin, on a
      // session minted for James (c-232).
      await james.goto(`${consoleUrl}/agents/${AGENT}?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const previewMinted = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/widget-deployments/${one.id}/preview-session`), { timeout: 90_000 }).catch(() => undefined);
      await james.locator(`[data-testid="widget-embed-row"][data-id="${one.id}"]`).getByTestId('widget-preview-open').click({ timeout: 60_000 });
      // The agent's greeting, inside the embed app's chat page that the loader frames in the preview.
      let shown = false;
      for (let i = 0; i < 90 && !shown; i++) {
        const chatFrame = james.frames().find((f) => f.url().includes(`/embed/${one.id}`));
        shown = chatFrame ? (await chatFrame.getByText(/^Hi James, I.m /).count()) > 0 : false;
        if (!shown) await james.waitForTimeout(1_000);
      }
      const session = await previewMinted;
      const failed = await james.getByTestId('widget-preview-error').count();
      check('4 Preview opens the embed’s real chat on a session minted for the builder', shown && session?.status() === 201 && failed === 0, { shown, session: session?.status(), failed, error: failed ? await james.getByTestId('widget-preview-error').innerText() : '' });

      // 4b A message sent from the Preview reaches the agent: the thread is opened, not refused for the page's origin.
      const chatFrame = james.frames().find((f) => f.url().includes(`/embed/${one.id}`));
      const opened = james.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/widget\/[^/]+\/threads$/.test(r.url()), { timeout: 60_000 }).catch(() => undefined);
      await chatFrame?.getByRole('textbox').first().fill('Hello from the preview');
      await chatFrame?.getByRole('textbox').first().press('Enter');
      const thread = await opened;
      check('4b a message sent from the Preview opens its thread (not refused for the origin)', thread?.status() === 201, { status: thread?.status(), said: thread ? (await thread.text()).slice(0, 200) : null });

      // 4c When the service refuses a send, the chat keeps the message and says why instead of dropping it.
      await chatFrame?.getByTestId('embed-new-conversation').count();
      await james.route(/\/v1\/widget\/[^/]+\/threads$/, (route) =>
        route.request().method() === 'POST'
          ? route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'origin_not_allowed', message: 'http://localhost:3020 may not use this embed.', status: 403 } }) })
          : route.continue(),
      );
      await chatFrame?.getByRole('button', { name: 'Chat menu' }).click();
      await chatFrame?.getByTestId('embed-new-conversation').click();
      await chatFrame?.getByRole('textbox').first().fill('Refused message');
      await chatFrame?.getByRole('textbox').first().press('Enter');
      const alert = chatFrame?.getByTestId('send-failed');
      const told = alert ? await alert.waitFor({ timeout: 30_000 }).then(async () => (await alert.innerText()).replace(/\s+/g, ' '), () => '') : '';
      await james.unroute(/\/v1\/widget\/[^/]+\/threads$/);
      check('4c a refused send stays in the chat with its reason and Retry', /wasn.t sent/.test(told) && /may not use this embed/.test(told) && /Retry/.test(told), { told });

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  // The embed app serves the loader and the chat frame the preview loads (c-232).
  { platform: true, embed: true },
);
finish();
