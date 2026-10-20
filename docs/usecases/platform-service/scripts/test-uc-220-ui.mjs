// uc-220 a person invited as a Security team admin, ui layer: docs/usecases/platform-service/role-security-admin.md.
// They open Settings > Sign-in and see the providers with Add provider; an admin of another team is told the Security
// team sets sign-in.
import { INVITED_PASSWORD, check, chromium, consoleSignIn, finish, invitePerson, withUiStack } from '@ops-ai/usecase-runner/harness';

const TAG = Math.random().toString(36).slice(2, 7);

await withUiStack(
  async (consoleUrl) => {
    await invitePerson('s.adeyemi@northfieldbank.com', `sec.${TAG}@northfieldbank.com`, 'admin', 'team_security');
    await invitePerson('p.shah@northfieldbank.com', `opsadmin.${TAG}@northfieldbank.com`, 'admin', 'team_ops');
    const browser = await chromium.launch();
    const errors = [];
    try {
      const sec = await consoleSignIn(browser, consoleUrl, `sec.${TAG}@northfieldbank.com`, INVITED_PASSWORD, errors);
      await sec.goto(`${consoleUrl}/settings/security/sign-in`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const listed = await sec.getByTestId('sign-in-providers').waitFor({ timeout: 90_000 }).then(() => true, () => false);
      check('the Security team admin sees the providers and Add provider', listed && (await sec.getByTestId('add-provider').count()) === 1);
      const other = await consoleSignIn(browser, consoleUrl, `opsadmin.${TAG}@northfieldbank.com`, INVITED_PASSWORD, errors);
      await other.goto(`${consoleUrl}/settings/security/sign-in`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const refused = await other.getByTestId('sign-in-no-access').waitFor({ timeout: 90_000 }).then(() => true, () => false);
      check("another team's admin is told the Security team sets sign-in, with no Add provider", refused && (await other.getByTestId('add-provider').count()) === 0);
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
