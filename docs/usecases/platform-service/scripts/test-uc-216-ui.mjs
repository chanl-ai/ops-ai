// uc-216 a person invited as a viewer, ui layer: docs/usecases/platform-service/role-viewer.md. Priya invites them;
// signed in, an agent page says View only and offers no Save, and Access offers no Invite.
import { INVITED_PASSWORD, check, chromium, consoleSignIn, finish, invitePerson, withUiStack } from '@ops-ai/usecase-runner/harness';

const EMAIL = `viewer.${Math.random().toString(36).slice(2, 7)}@harborpine.example`;

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
      await page.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('row', { name: /Priya Shah/ }).waitFor({ timeout: 60_000 });
      check('Access offers the viewer no Invite', (await page.getByTestId('access-invite').count()) === 0);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
