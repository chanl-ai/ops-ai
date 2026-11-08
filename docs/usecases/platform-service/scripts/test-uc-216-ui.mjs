// uc-216 a person invited as a viewer, ui layer: docs/usecases/platform-service/role-viewer.md. Priya invites them;
// signed in, an agent page says View only and offers no Save or Test, Access offers no Invite, and Channels offers no
// Connect, Manage or Embed. James, a builder, is offered each of them, so the checks cannot pass on an empty page.
import { INVITED_PASSWORD, check, chromium, consoleSignIn, finish, invitePerson, withUiStack } from '@ops-ai/usecase-runner/harness';

const EMAIL = `viewer.${Math.random().toString(36).slice(2, 7)}@harborpine.example`;

/** The set-up controls Channels shows: the hub's Connect channel, the built kinds' card actions, and the chat kind's Embed. */
async function channelControls(page, consoleUrl) {
  await page.goto(`${consoleUrl}/channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('channel-gallery').waitFor({ timeout: 90_000 });
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
  const connect = await page.getByTestId('connect-channel').count();
  const cards = await page.locator('[data-testid^="gallery-action-"]', { hasText: /^(Connect|Manage)$/ }).count();
  await page.goto(`${consoleUrl}/channels/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByRole('heading', { name: 'Chat embed' }).first().waitFor({ timeout: 90_000 });
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
  return { connect, cards, embed: await page.getByTestId('widget-embed-open').count() };
}

await withUiStack(
  async (consoleUrl) => {
    await invitePerson('p.shah@harborpine.example', EMAIL, 'viewer');
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, EMAIL, INVITED_PASSWORD, errors);
      await page.goto(`${consoleUrl}/agents/ag_branch`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const notice = await page.getByTestId('read-only-notice').waitFor({ timeout: 90_000 }).then(() => true, () => false);
      const save = await page.getByRole('button', { name: /^Save/ }).count();
      check('an agent page tells the viewer View only and offers no Save', notice && save === 0, { notice, save });
      await page.getByRole('tab', { name: 'Versions' }).waitFor({ timeout: 60_000 });
      const testing = { button: await page.getByTestId('test-agent-button').count(), tab: await page.getByTestId('test-tab').count() };
      check('an agent page offers the viewer no Test', testing.button === 0 && testing.tab === 0, testing);
      await page.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('row', { name: /Priya Shah/ }).waitFor({ timeout: 60_000 });
      check('Access offers the viewer no Invite', (await page.getByTestId('access-invite').count()) === 0);
      const viewer = await channelControls(page, consoleUrl);
      check('Channels offers the viewer no Connect, Manage or Embed', Object.values(viewer).every((n) => n === 0), viewer);
      const builder = await channelControls(await consoleSignIn(browser, consoleUrl, 'j.richardson@harborpine.example', 'northfield-demo', errors), consoleUrl);
      check('Channels offers a builder Connect channel, each built kind its action, and Embed', builder.connect === 1 && builder.cards > 0 && builder.embed === 1, builder);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
