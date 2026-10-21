// uc-219 a person invited as an admin, ui layer: docs/usecases/platform-service/role-admin.md. On Access the new admin
// invites a person as viewer through the dialog; the person accepts the link; the admin changes their role to Builder
// with Change role; the person's next sign-in carries Builder.
import { INVITED_PASSWORD, PLATFORM_PORT, check, chromium, consoleSignIn, finish, invitePerson, withUiStack } from '@ops-ai/usecase-runner/harness';

const TAG = Math.random().toString(36).slice(2, 7);
const ADMIN = `admin.${TAG}@harborpine.example`;
const PERSON = `person.${TAG}@harborpine.example`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;

await withUiStack(
  async (consoleUrl) => {
    await invitePerson('p.shah@harborpine.example', ADMIN, 'admin');
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, ADMIN, INVITED_PASSWORD, errors);
      await page.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('access-invite').click({ timeout: 90_000 });
      const dialog = page.getByRole('dialog');
      await dialog.getByRole('textbox').first().fill(PERSON);
      await dialog.getByRole('radio', { name: /Viewer/ }).click();
      await dialog.getByRole('button', { name: /^Invite/ }).click();
      const link = await page.getByRole('textbox', { name: `Invitation link for ${PERSON}` }).inputValue({ timeout: 30_000 });
      await page.getByRole('button', { name: 'Done' }).click();
      const token = link.split('/invite/')[1];
      const accepted = await (await fetch(`${platform}/v1/invites/${token}/accept`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: `Person ${TAG}`, password: INVITED_PASSWORD }) })).json();
      check('the admin invites a person from Access, who joins as viewer', accepted.data?.principal?.roles?.team_ops === 'viewer', accepted.data?.principal?.roles);

      await page.reload({ waitUntil: 'domcontentloaded' });
      const row = page.getByRole('row', { name: new RegExp(`Person ${TAG}`, 'i') });
      await row.waitFor({ timeout: 60_000 });
      await row.getByRole('button').last().click();
      await page.getByRole('menuitem', { name: 'Change role' }).click();
      await page.getByRole('dialog').getByRole('combobox').click();
      await page.getByRole('option', { name: 'Builder' }).click();
      await page.getByRole('button', { name: 'Change role' }).click();
      const shown = await row.getByText('Builder').waitFor({ timeout: 30_000 }).then(() => true, () => false);
      const next = await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: PERSON, password: INVITED_PASSWORD }) })).json();
      check('Change role makes them Builder, in the list and in their next token', shown && next.data?.principal?.roles?.team_ops === 'builder', { shown, roles: next.data?.principal?.roles });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
