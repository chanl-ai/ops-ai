// uc-199 a builder connects a team mailbox in the console and binds a workflow to it, ui layer:
// docs/usecases/agents-service/connect-a-mailbox.md (c-199). withUiStack with platform sign-in and tools-service, run
// isolated (ISOLATED=1). Sam puts the mailbox password on the Secrets page through the API; James connects an IMAP
// mailbox on Channels > Email, tests it, opens its page, then connects a second mailbox from a workflow's Email
// received trigger and saves the version, which names the new mailbox.
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const PASSWORD = 'northfield-demo';
const SECRET = 'DESK_IMAP_PASSWORD';
const RUN = Math.random().toString(36).slice(2, 8);
const DESK = `desk-${RUN}@harborpine.test`;
const LEVY = `levies-${RUN}@gmail.com`;
const tokenFor = async (email) =>
  (
    await (
      await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })
    ).json()
  ).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });

const WORKFLOW = {
  schemaVersion: 2,
  id: `uc199_${RUN}`,
  name: 'Desk intake by email',
  nodes: [
    { id: 'start', type: 'ops.trigger.email', typeVersion: 1, name: 'Email arrives', parameters: { mailbox: 'levy@harborpine.example' }, position: { x: 0, y: 0 } },
    { id: 'done', type: 'ops.flow.end', typeVersion: 1, name: 'Done', parameters: {}, position: { x: 300, y: 0 } },
  ],
  connections: [{ from: { node: 'start', port: 'payload' }, to: { node: 'done', port: 'in' } }],
};

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    return undefined;
  }
}

async function pickSecret(page, id) {
  await page.locator(`#${id}`).click();
  await page.getByRole('option', { name: new RegExp(SECRET) }).click();
}

await withUiStack(
  async (consoleUrl) => {
    const S = as(await tokenFor(SAM), 'team_security');
    const J = as(await tokenFor(JAMES), 'team_ops');
    const secret = await fetch(`${tools}/v1/secrets`, { method: 'POST', headers: S, body: JSON.stringify({ name: SECRET, value: 'app-password', teamId: 'team_ops' }) });
    const saved = await (await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition: WORKFLOW }) })).json();
    check('0 the secret is on the Secrets page and the draft workflow is saved', secret.status === 201 && !!saved.data?.version, { secret: secret.status, saved });

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page
        .getByRole('button', { name: /^Sign in/ })
        .first()
        .click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await step('1 Channels lists the team mailboxes from the records', async () => {
        await page.goto(`${consoleUrl}/channels/email`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        // The Email mailbox page lists the team's mailboxes from the channel records (c-242).
        const list = page.getByRole('table');
        await list.locator('[data-testid^="channel-row-"]').first().waitFor({ timeout: 60_000 });
        const text = await list.innerText();
        check('1 Channels lists the team mailboxes from the records', /levy@harborpine\.example/.test(text) && /intake@harborpine\.test/.test(text), text);
      });

      await step('2 James connects an IMAP mailbox, tests it and lands on its page', async () => {
        await page.getByTestId('connect-mailbox').click();
        await page.getByLabel('Other IMAP').click();
        await page.getByTestId('connect-mailbox-submit').click();
        await page.locator('#connect-page-name').fill(`Service desk ${RUN}`);
        await page.locator('#connect-page-address').fill(DESK);
        await page.locator('#connect-page-host').fill('mail.harborpine.test');
        await page.locator('#connect-page-port').fill('143');
        await page.locator('#connect-page-tls').click();
        await pickSecret(page, 'connect-page-secret');
        await page.getByTestId('mailbox-test-run').click();
        const result = page.getByTestId('mailbox-test-result');
        await result.waitFor({ timeout: 60_000 });
        // This isolated tools-service has no route to GreenMail, so the test reports the refused host: the form shows
        // the server's answer and never a Connected it did not get.
        const tested = { ok: await result.getAttribute('data-ok'), text: await result.innerText() };
        await page.getByTestId('connect-mailbox-submit').click();
        await page.getByTestId('mailbox-page').waitFor({ timeout: 60_000 });
        const title = page.url().includes('/channels/email/mbx_') ? await page.getByText(`Service desk ${RUN}`).first().innerText() : page.url();
        check('2 James connects an IMAP mailbox, tests it and lands on its page', tested.ok === 'false' && /allow-list|Could not connect/.test(tested.text) && title.includes(`Service desk ${RUN}`), {
          tested,
          title,
        });
      });

      await step('2b James connects a Microsoft 365 mailbox with its app registration, replying through Graph', async () => {
        await page.goto(`${consoleUrl}/channels/email`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('connect-mailbox').click();
        await page.getByLabel('Microsoft 365').click();
        await page.getByTestId('connect-mailbox-submit').click();
        await page.locator('#connect-page-name').fill(`Lending ${RUN}`);
        await page.locator('#connect-page-address').fill(`lending-${RUN}@harborpine.example`);
        // An IMAP host and user name mean nothing to Microsoft 365: the form asks for the app registration instead.
        const imapAsked = (await page.locator('#connect-page-host').count()) + (await page.locator('#connect-page-username').count());
        await page.locator('#connect-page-graphTenantId').fill('harborpine.onmicrosoft.com');
        await page.locator('#connect-page-graphClientId').fill('3f1c2b7a-0d4e-4c1a-9b8e-2a6f5d7c9e10');
        await pickSecret(page, 'connect-page-secret');
        await page.getByTestId('mailbox-replies').getByLabel('Microsoft 365').click();
        const fromAsked = await page.locator('#connect-page-fromAddress').count();
        await page.getByTestId('mailbox-test-run').click();
        const result = page.getByTestId('mailbox-test-result');
        await result.waitFor({ timeout: 60_000 });
        const tested = { ok: await result.getAttribute('data-ok'), text: await result.innerText() };
        await page.getByTestId('connect-mailbox-submit').click();
        await page.getByTestId('mailbox-page').waitFor({ timeout: 60_000 });
        const mid = /\/channels\/email\/(mbx_[^/?#]+)/.exec(page.url())?.[1];
        const saved = mid ? (await (await fetch(`${agents}/v1/channels/mailboxes/${mid}`, { headers: J })).json()).data : null;
        check(
          '2b James connects a Microsoft 365 mailbox with its app registration, replying through Graph',
          imapAsked === 0 &&
            fromAsked === 0 &&
            tested.ok !== null &&
            saved?.provider === 'graph' &&
            saved.graphTenantId === 'harborpine.onmicrosoft.com' &&
            saved.graphClientId === '3f1c2b7a-0d4e-4c1a-9b8e-2a6f5d7c9e10' &&
            saved.passwordSecret === SECRET &&
            saved.sender === 'graph',
          { imapAsked, fromAsked, tested, saved: saved && { provider: saved.provider, tenant: saved.graphTenantId, client: saved.graphClientId, secret: saved.passwordSecret, sender: saved.sender } },
        );
      });

      await step('3 Connect a mailbox from the trigger sheet fills the trigger, and the saved version keeps it', async () => {
        await page.goto(`${consoleUrl}/workflows/definitions/${WORKFLOW.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const canvas = page.getByTestId('definition-canvas');
        await canvas.locator('[data-testid="definition-node"]').first().waitFor({ timeout: 120_000 });
        await page.waitForTimeout(500);
        await canvas.locator('[data-node-id="start"]').dblclick();
        await page.getByTestId('trigger-connect-mailbox').click();
        await page.getByTestId('connect-mailbox-submit').click(); // Gmail is the first provider
        await page.locator('#connect-dialog-name').fill(`Levies ${RUN}`);
        await page.locator('#connect-dialog-address').fill(LEVY);
        await pickSecret(page, 'connect-dialog-secret');
        await page.getByTestId('connect-mailbox-submit').click();
        await page.getByRole('dialog', { name: 'Connect a mailbox' }).waitFor({ state: 'detached', timeout: 30_000 });
        await page.getByTestId('definition-save').click();
        let mailbox = null;
        for (let i = 0; i < 30; i++) {
          const latest = await (await fetch(`${agents}/v1/workflows/definitions/${WORKFLOW.id}`, { headers: J })).json();
          if (latest.data?.version === 2) {
            mailbox = latest.data.definition.nodes.find((n) => n.id === 'start').parameters.mailbox;
            break;
          }
          await page.waitForTimeout(500);
        }
        const listed = (await (await fetch(`${agents}/v1/channels/mailboxes`, { headers: J })).json()).data.map((m) => m.address);
        check('3 Connect a mailbox from the trigger sheet fills the trigger, and the saved version keeps it', mailbox === LEVY && listed.includes(LEVY) && listed.includes(DESK), { mailbox, listed });
      });

      await step('3b the trigger shows the picked mailbox with its state and a link to it, and warns while it is paused', async () => {
        const levy = (await (await fetch(`${agents}/v1/channels/mailboxes`, { headers: J })).json()).data.find((m) => m.address === LEVY);
        const openTrigger = async () => {
          await page.goto(`${consoleUrl}/workflows/definitions/${WORKFLOW.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const canvas = page.getByTestId('definition-canvas');
          await canvas.locator('[data-testid="definition-node"]').first().waitFor({ timeout: 120_000 });
          await page.waitForTimeout(500);
          await canvas.locator('[data-node-id="start"]').dblclick();
          await page.getByTestId('trigger-picked-mailbox').waitFor({ timeout: 30_000 });
        };
        await openTrigger();
        const row = (await page.getByTestId('trigger-picked-mailbox').innerText()).replace(/\s+/g, ' ');
        const href = await page.getByTestId('trigger-picked-mailbox').getByRole('link', { name: 'Open' }).getAttribute('href');
        const warnedBefore = await page.getByTestId('trigger-mailbox-paused').count();
        const paused = await fetch(`${agents}/v1/channels/${levy.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ paused: true }) });
        await openTrigger();
        const warned = await page.getByTestId('trigger-mailbox-paused').count();
        await fetch(`${agents}/v1/channels/${levy.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ paused: false }) });
        check(
          '3b the trigger shows the picked mailbox with its state and a link to it, and warns while it is paused',
          row.includes(`Levies ${RUN}`) && href === `/channels/email/${levy.id}` && warnedBefore === 0 && paused.status < 300 && warned === 1,
          { row, href, warnedBefore, paused: paused.status, warned },
        );
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { gateway: true }, agentsEnv: { OPS_MAILBOXES_SEED_FILE: 'seed/mailboxes.json' } },
);

finish();
