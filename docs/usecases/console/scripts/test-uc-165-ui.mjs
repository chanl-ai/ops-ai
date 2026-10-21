// uc-165 the channels mock connects a mailbox and a trigger picks it, ui layer: docs/usecases/console/channels-preview.md.
// Signed in through platform-service as James (builder). The mock lives under /preview/channels on sample data held in
// the page's memory, so the walk moves by clicking links: a full page load would start the sample over.
import { PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const ROOT = '/preview/channels';
const MAILBOX = 'levy.notices.test@gmail.com';

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    return undefined;
  }
}

const signIn = async (browser, consoleUrl, width = 1440) => {
  const page = await (await browser.newContext({ viewport: { width, height: 1000 } })).newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  page.on('console', (m) => m.type() === 'error' && !/favicon|Failed to load resource/.test(m.text()) && page.errors.push(m.text()));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(JAMES);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
};
const open = async (page, consoleUrl, path) => {
  await page.goto(`${consoleUrl}${ROOT}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('page-title').first().waitFor({ timeout: 120_000 });
};
const pickOption = async (page, trigger, name) => {
  await page.locator(trigger).click();
  await page.getByRole('option', { name }).first().click();
};

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const p = await signIn(browser, consoleUrl);

      await step('1 the gallery shows six kinds, three coming soon, and every connection with its status', async () => {
        await open(p, consoleUrl, '');
        const cards = await p.locator('[data-testid^="gallery-"]:not([data-testid^="gallery-action"])').evaluateAll((els) => els.map((e) => e.innerText));
        const soon = cards.filter((t) => t.includes('Coming soon')).map((t) => t.split('\n')[0]);
        const table = await p.getByRole('table').innerText();
        const head = await p.getByRole('table').locator('thead').innerText();
        check(
          '1 the gallery shows six kinds, three coming soon, and every connection with its status',
          cards.length === 6 && soon.join() === 'MCP,Slack,Teams' && ['Connected', 'Needs attention', 'Paused'].every((s) => table.includes(s)) && /\bId\b/.test(head) && (await p.getByRole('checkbox', { name: /select all/i }).count()) === 1,
          { cards: cards.length, soon, head },
        );
      });

      await step('1b a mailbox row opens its settings drawer with status, last message and workflows', async () => {
        await p.getByTestId('connection-mbx_5d92a6f3').getByRole('button', { name: /Disputes test inbox/ }).click();
        const sheet = p.getByTestId('mailbox-sheet');
        await sheet.waitFor({ timeout: 10_000 });
        const text = await sheet.innerText();
        check('1b a mailbox row opens its settings drawer with status, last message and workflows', /Needs attention/.test(text) && /Test dispute 31/.test(text) && /Card dispute resolution/.test(text) && (await sheet.locator('#sheet-secret').innerText()).includes('DISPUTES_APP_PASSWORD'), text.slice(0, 300));
        await p.keyboard.press('Escape');
        await sheet.waitFor({ state: 'detached', timeout: 10_000 });
      });

      await step('2 the connect form asks for a provider, then sign-in, folder and sender', async () => {
        await p.getByTestId('gallery-action-email').click();
        await p.getByTestId('connect-mailbox').click();
        await p.getByTestId('connect-mailbox-steps').waitFor({ timeout: 60_000 });
        const providers = await p.getByRole('radio').evaluateAll((els) => els.map((e) => e.closest('label')?.innerText.split('\n')[0]));
        await p.getByRole('radio', { name: /Gmail/ }).click();
        await p.getByTestId('connect-mailbox-submit').click();
        await p.getByTestId('mailbox-fields').waitFor({ timeout: 10_000 });
        const fields = await p.getByTestId('mailbox-fields').innerText();
        check('2 the connect form asks for a provider, then sign-in, folder and sender', providers.join() === 'Gmail,Microsoft 365,Other IMAP' && /App password/.test(fields) && /Folder/.test(fields) && /Send replies with|SMTP/.test(fields) && !(await p.locator('#connect-secret[type="password"], input#connect-secret').count()), { providers, fields: fields.slice(0, 300) });
      });

      await step('3 a test before a secret is picked fails at sign-in and says why', async () => {
        await p.locator('#connect-name').fill('Levy notices');
        await p.locator('#connect-address').fill(MAILBOX);
        await p.getByTestId('mailbox-test-run').click();
        const result = p.getByTestId('mailbox-test-result');
        await result.waitFor({ timeout: 10_000 });
        check('3 a test before a secret is picked fails at sign-in and says why', (await result.getAttribute('data-ok')) === 'false' && /Pick the secret/.test(await result.innerText()), await result.innerText());
      });

      await step('4 a secret added from the field fills it, and the test then reads the folder', async () => {
        await p.getByTestId('connect-secret-add').click();
        await p.locator('#secret-name').fill('LEVY_APP_PASSWORD');
        await p.locator('#secret-value').fill('abcd efgh ijkl mnop');
        await p.getByRole('button', { name: 'Save secret' }).click();
        await p.locator('#secret-name').waitFor({ state: 'detached', timeout: 10_000 });
        const filled = await p.locator('#connect-secret').innerText();
        await pickOption(p, '#connect-folder', 'Levies');
        await p.getByTestId('connect-senderSecret-add').waitFor();
        await pickOption(p, '#connect-senderSecret', 'LEVY_APP_PASSWORD');
        await p.getByTestId('mailbox-test-run').click();
        await p.locator('[data-testid="mailbox-test-result"][data-ok="true"]').waitFor({ timeout: 10_000 });
        const steps = await p.getByTestId('mailbox-test').innerText();
        const valueLeft = (await p.content()).includes('abcd efgh ijkl mnop');
        check('4 a secret added from the field fills it, and the test then reads the folder', filled.includes('LEVY_APP_PASSWORD') && /Sign in/.test(steps) && /Open Levies/.test(steps) && /Read the newest message/.test(steps) && /Connected/.test(steps) && !valueLeft, { filled, steps, valueLeft });
      });

      await step('5 connecting lands on the mailbox page, which no workflow watches yet', async () => {
        await p.getByTestId('connect-mailbox-submit').click();
        await p.getByTestId('mailbox-workflows-empty').waitFor({ timeout: 10_000 });
        const title = await p.getByTestId('page-title').first().innerText();
        check('5 connecting lands on the mailbox page, which no workflow watches yet', title.includes('Levy notices') && /\/preview\/channels\/email\/mbx_/.test(p.url()), { title, url: p.url() });
      });

      await step('6 the trigger mock offers the new mailbox in its picker', async () => {
        await p.getByRole('link', { name: 'trigger mock' }).click();
        await p.getByTestId('trigger-sheet').waitFor({ timeout: 60_000 });
        await p.locator('#trigger-mailbox').click();
        const offered = await p.getByRole('option').allInnerTexts();
        check('6 the trigger mock offers the new mailbox in its picker', offered.some((o) => o.includes('Levy notices') && o.includes(MAILBOX)), offered);
        await p.getByRole('option', { name: /Levy notices/ }).click();
      });

      await step('7 saving binds the workflow, and the mailbox page lists it with a link', async () => {
        await p.getByTestId('trigger-save').click();
        const how = await p.getByTestId('trigger-sheet').innerText();
        await p.getByTestId('trigger-picked').getByRole('link', { name: 'Open' }).click();
        const rows = p.getByTestId('mailbox-workflows');
        await rows.waitFor({ timeout: 10_000 });
        const href = await rows.getByRole('link').first().getAttribute('href');
        check('7 saving binds the workflow, and the mailbox page lists it with a link', how.includes(`A new email in ${MAILBOX}, folder Levies`) && (await rows.innerText()).includes('Levy notice intake') && href === '/workflows/wf_levy_intake', { href });
      });

      await step('8 Connect a mailbox on the trigger opens the same form as a dialog and fills the picker', async () => {
        await p.goBack();
        await p.getByTestId('trigger-sheet').waitFor({ timeout: 60_000 });
        await p.getByTestId('trigger-connect-mailbox').click();
        const dialog = p.getByRole('dialog', { name: 'Connect a mailbox' });
        await dialog.waitFor({ timeout: 10_000 });
        const steps = await dialog.getByTestId('connect-mailbox-steps').count();
        await dialog.getByRole('radio', { name: /Other IMAP/ }).click();
        await dialog.getByTestId('connect-mailbox-submit').click();
        await dialog.locator('#connect-name').fill('Court filings');
        await dialog.locator('#connect-address').fill('filings@harborpine.example');
        await dialog.locator('#connect-host').fill('mail.harborpine.example');
        await pickOption(p, '#connect-secret', 'KYB_MAILBOX_PASSWORD');
        await dialog.locator('#connect-smtpHost').fill('smtp.harborpine.example:587');
        await pickOption(p, '#connect-senderSecret', 'KYB_MAILBOX_PASSWORD');
        await dialog.getByTestId('connect-mailbox-submit').click();
        await dialog.waitFor({ state: 'detached', timeout: 10_000 });
        const picked = await p.locator('#trigger-mailbox').innerText();
        check('8 Connect a mailbox on the trigger opens the same form as a dialog and fills the picker', steps === 1 && picked.includes('Court filings'), { steps, picked });
      });

      await step('10 a tab per channel kind carries a health dot; kinds coming soon carry none', async () => {
        await open(p, consoleUrl, '');
        const health = Object.fromEntries(await p.locator('[data-testid^="channel-tab-"]').evaluateAll((els) => els.map((e) => [e.getAttribute('data-testid').slice('channel-tab-'.length), e.getAttribute('data-health')])));
        check('10 a tab per channel kind carries a health dot; kinds coming soon carry none', health.email === 'warn' && health.chat === 'ok' && health.api === 'ok' && health.mcp === 'soon' && health.slack === 'soon', health);
      });

      await step('11 a channel landing counts its activity and opens the Activity page filtered to it', async () => {
        await p.getByTestId('channel-tab-email').click();
        const landing = p.getByTestId('channel-activity-email');
        const count = (await landing.innerText({ timeout: 30_000 })).split('\n')[0];
        await landing.getByRole('link', { name: /View activity/ }).click();
        await p.waitForURL(/\/preview\/channels\/activity\?channel=email/, { timeout: 30_000 });
        const channels = await p.getByRole('table').locator('tbody tr td:nth-child(4)').allInnerTexts();
        check('11 a channel landing counts its activity and opens the Activity page filtered to it', /^[\d,]+$/.test(count) && channels.length > 0 && channels.every((c) => c === 'Email mailbox'), { count, channels });
      });

      await step('12 what a connection serves changes in place, and the agent page shows the version moved', async () => {
        await open(p, consoleUrl, '');
        const before = await p.getByTestId('serves-emb_4f0e2b9d').innerText();
        await p.getByTestId('serves-emb_4f0e2b9d').getByRole('combobox', { name: /^Version/ }).click();
        await p.getByRole('option', { name: /^Latest/ }).click();
        const after = await p.getByTestId('serves-emb_4f0e2b9d').innerText();
        // Client navigation keeps the mock's state; the agent page reads the same connections.
        await p.getByTestId('channel-tab-chat').click();
        await p.getByRole('link', { name: /Channels tab/ }).click();
        await p.getByTestId('agent-version-5').waitFor({ timeout: 30_000 });
        const v5 = await p.getByTestId('agent-version-5').innerText();
        const v4 = await p.getByTestId('agent-version-4').count();
        check('12 what a connection serves changes in place, and the agent page shows the version moved', /v4 pinned/.test(before) && /Latest · v5/.test(after) && /Wealth portal/.test(v5) && v4 === 0, { before, after, v5, v4 });
      });

      await step('13 the old Deployments address lands on Channels and says so', async () => {
        await p.goto(`${consoleUrl}/preview/deployments`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await p.waitForURL(/\/preview\/channels\?from=deployments/, { timeout: 30_000 });
        const said = await p.getByText('Deployments are now Channels').count();
        check('13 the old Deployments address lands on Channels and says so', said === 1, { url: p.url(), said });
      });

      check('every page walked without a console error', p.errors.length === 0, p.errors.slice(0, 5));

      await step('9 at 400 px the channels, email, agent, activity and trigger pages do not scroll sideways', async () => {
        const phone = await signIn(browser, consoleUrl, 400);
        const widths = {};
        for (const path of ['', '/trigger', '/email', '/agent', '/activity']) {
          await open(phone, consoleUrl, path);
          await phone.waitForTimeout(500);
          widths[path || '/'] = await phone.evaluate(() => document.documentElement.scrollWidth);
        }
        check('9 at 400 px the channels, email, agent, activity and trigger pages do not scroll sideways', Object.values(widths).every((w) => w <= 400), widths);
      });
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
