// uc-517 the console has no preview mock pages, ui layer: docs/usecases/console/real-pages-not-mocks.md (c-517). A
// private stack with platform sign-in and tools-service. The pieces the mocks drew that the real pages lacked: an
// agent's ID to copy, and adding an allowed host from a tool whose request goes to an unlisted one, in place, with the
// Egress page's form. The former preview routes answer 404, except human-tasks, which waits on the owner's layout choice.
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const HOST = 'statements.uc517.example';
const SHOTS = evidenceDir('517', 'uc');
const tokenFor = async (email) =>
  (
    await (
      await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })
    ).json()
  ).data.token;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

/** The Import operations dialog on step 2, building one HTTP operation whose request goes to `url`. */
async function httpBuilder(page, consoleUrl, url) {
  await page.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('import-operations').click({ timeout: 120_000 });
  await page.locator('label[for="mk-http"]').click();
  await page.getByTestId('import-next').click();
  await page.locator('#http-url').fill(url);
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      await step('1 an agent’s Settings tab shows its ID to copy', async () => {
        const james = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops' };
        const agent = (await (await fetch(`http://127.0.0.1:${AGENTS_PORT}/v1/agents?pageSize=1`, { headers: james })).json()).data?.data?.[0];
        if (!agent) throw new Error('setup: no agent in Operations');
        const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
        await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const field = page.locator('#ag-id');
        await field.waitFor({ timeout: 60_000 });
        const shown = await field.inputValue();
        const copy = await page.getByRole('button', { name: 'Copy agent ID' }).count();
        await page.screenshot({ path: join(SHOTS, 'agent-id-1280.png') });
        check('1 an agent’s Settings tab shows its ID to copy', shown === agent.id && copy === 1, { shown, id: agent.id, copy });
        await page.context().close();
      });

      await step('2 a builder sees that the request’s host is not allowed, and who can add it', async () => {
        const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
        await httpBuilder(page, consoleUrl, `https://${HOST}/v1/accounts/{accountId}/statements`);
        const notice = page.getByTestId('egress-host-notice');
        await notice.waitFor({ timeout: 30_000 });
        const text = (await notice.innerText()).replace(/\s+/g, ' ');
        const button = await page.getByTestId('egress-host-add').count();
        check('2 a builder sees that the request’s host is not allowed, and who can add it', text.includes(`${HOST} is not an allowed host`) && /Security admin/.test(text) && button === 0, {
          text,
          button,
        });
        await page.context().close();
      });

      await step('3 a Security admin adds the host in place with the Egress form; the import stays open', async () => {
        const page = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
        await httpBuilder(page, consoleUrl, `https://${HOST}/v1/accounts/{accountId}/statements`);
        await page.getByTestId('egress-host-add').click({ timeout: 30_000 });
        const preset = await page.locator('#egress-value').inputValue();
        await page.screenshot({ path: join(SHOTS, 'add-host-in-place-1280.png') });
        await page.getByTestId('egress-add-submit').click();
        await page.getByTestId('egress-host-notice').waitFor({ state: 'detached', timeout: 30_000 });
        const stillOpen = await page.locator('#http-url').isVisible();
        const sam = { Authorization: `Bearer ${await tokenFor(SAM)}`, 'X-Team-Id': 'team_security' };
        const listed = (await (await fetch(`http://127.0.0.1:${TOOLS_PORT}/v1/egress`, { headers: sam })).json()).data?.hosts?.map((h) => h.host) ?? [];
        check('3 a Security admin adds the host in place with the Egress form; the import stays open', preset === HOST && stillOpen && listed.includes(HOST), { preset, stillOpen, listed });
        await page.context().close();
      });

      await step('4 the former preview pages are gone; human-tasks stays', async () => {
        const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
        const status = {};
        for (const path of ['home', 'case-story', 'start-run', 'deployments', 'access/roles', 'channels', 'settings', 'workflow-layout', 'human-tasks']) {
          status[path] = (await page.goto(`${consoleUrl}/preview/${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 }))?.status();
        }
        const gone = Object.entries(status).filter(([p]) => p !== 'human-tasks');
        check('4 the former preview pages are gone; human-tasks stays', gone.every(([, s]) => s === 404) && status['human-tasks'] === 200, status);
        await page.context().close();
      });
      check('5 no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);
finish();
