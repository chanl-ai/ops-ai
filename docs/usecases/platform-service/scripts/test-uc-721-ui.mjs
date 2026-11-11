// uc-721 a team admin gives a system its own expiring, rotatable key limited to picked tools, ui layer. Headless
// Chromium against a console signed in through platform-service (dev seed, tools-service beside it for the tool
// picker): Priya (team_ops admin) opens Create key, sees a tool picker and no "Never" expiry, makes a key, finds a key
// 10 days from its end marked "Expires soon" at 1440 and 390, rotates it, and sees a key whose maker left marked gone;
// James (builder) sees the no-access state; the list is faked empty and failing for the two states a mock would draw.
import { INVITED_PASSWORD, PLATFORM_PORT, check, chromium, consoleSignIn, finish, invitePerson, withUiStack } from '@ops-ai/usecase-runner/harness';

const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const json = { 'Content-Type': 'application/json' };
const post = async (path, headers, body) => (await fetch(`${platform}${path}`, { method: 'POST', headers: { ...json, ...headers }, body: JSON.stringify(body) })).json();
const shown = (locator, ms = 30_000) => locator.waitFor({ timeout: ms }).then(() => true, () => false);

await withUiStack(
  async (consoleUrl) => {
    const signIn = await post('/v1/auth/sign-in', {}, { email: 'p.shah@harborpine.example', password: 'northfield-demo' });
    const priya = { Authorization: `Bearer ${signIn.data.token}`, 'X-Team-Id': 'team_ops' };
    const base = { scopes: ['read'], expiresInDays: 90 };
    await post('/v1/api-keys', priya, { ...base, name: 'Near its end', expiresInDays: 10 });
    // A key whose maker left: a second admin makes it and Priya removes them.
    const ravi = await invitePerson('p.shah@harborpine.example', 'ravi.maker@harborpine.example', 'admin');
    await post('/v1/api-keys', { Authorization: `Bearer ${ravi}`, 'X-Team-Id': 'team_ops' }, { ...base, name: 'Ravi export' });
    const members = await (await fetch(`${platform}/v1/settings/members`, { headers: priya })).json();
    const gone = members.data.data.find((m) => m.email === 'ravi.maker@harborpine.example');
    await post('/v1/settings/members/delete', priya, { ids: [gone.id] });
    await invitePerson('p.shah@harborpine.example', 'james.member@harborpine.example', 'builder');

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, 'p.shah@harborpine.example', 'northfield-demo', errors);
      await page.goto(`${consoleUrl}/settings/team/api-keys`, { waitUntil: 'domcontentloaded', timeout: 120_000 });

      // 7. The dialog: tools are picked, and an expiry is not optional.
      // dispatchEvent: the button stays animating for Playwright's stability check on this page, so a plain click times out.
      await page.getByRole('button', { name: 'Create key' }).first().dispatchEvent('click', undefined, { timeout: 90_000 });
      const dialog = page.getByRole('dialog');
      check('7 Create key offers a tool picker', await shown(dialog.getByText(/Tools/).first()));
      await dialog.getByLabel('Expires').click();
      check('7 and no "Never" expiry', (await page.getByRole('option', { name: 'Never' }).count()) === 0);
      await page.getByRole('option', { name: '90 days' }).click();
      await dialog.getByLabel('Name').fill('Claims triage script');
      await dialog.getByRole('button', { name: /^Create/ }).click();
      check('7 the secret shows once, to copy', await shown(page.getByText('Copy your API key')));
      await page.getByRole('button', { name: /stored the key/ }).click();

      // 8. Near its end, at both widths; the maker gone; Rotate.
      for (const [width, height] of [[1440, 1000], [390, 844]]) {
        await page.setViewportSize({ width, height });
        await page.reload({ waitUntil: 'domcontentloaded' });
        const row = page.getByRole('row', { name: /Near its end/ });
        check(`8 ${width}: a key within 14 days says "Expires soon"`, await shown(row.getByText('Expires soon'), 60_000));
        check(`8 ${width}: the key whose maker left shows the maker as gone`, await shown(page.getByRole('row', { name: /Ravi export/ }).getByText(/gone/i), 30_000));
        check(`8 ${width}: no row below 14 days is marked on a 90-day key`, (await page.getByRole('row', { name: /Claims triage script/ }).getByText('Expires soon').count()) === 0);
      }
      await page.setViewportSize({ width: 1440, height: 1000 });
      const row = page.getByRole('row', { name: /Claims triage script/ });
      await row.getByRole('button').last().click();
      await page.getByRole('menuitem', { name: /Rotate/ }).click();
      await page.getByRole('dialog').getByRole('button', { name: /Rotate/ }).last().click();
      check('9 Rotate shows the new secret once', await shown(page.getByText('Copy your API key')));
      await page.getByRole('button', { name: /stored the key/ }).click();

      // 10. A member, then the list empty and failing.
      const member = await consoleSignIn(browser, consoleUrl, 'james.member@harborpine.example', INVITED_PASSWORD, errors);
      await member.goto(`${consoleUrl}/settings/team/api-keys`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      check('10 a member sees the no-access state', await shown(member.getByTestId('query-forbidden'), 60_000));
      await page.route('**/v1/api-keys*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: [] }) }));
      await page.reload({ waitUntil: 'domcontentloaded' });
      check('10 an empty list draws the empty state with Create key', await shown(page.getByText(/Create a key for each system/), 60_000));
      await page.unroute('**/v1/api-keys*');
      await page.route('**/v1/api-keys*', (route) => route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'internal', message: 'down', status: 500 } }) }));
      await page.reload({ waitUntil: 'domcontentloaded' });
      check('10 a failing list draws the error state with retry', await shown(page.getByRole('button', { name: /retry|try again/i }), 60_000));
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);
finish();
