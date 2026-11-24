// uc-002 write tool pauses and approval resumes with step-up, ui layer:
// docs/usecases/agents-service/write-tool-approval-step-up.md. Headless Chromium against a console whose chat
// calls the agents service on the scripted model; the mock signs in the default user.
import { PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PASSWORD = 'northfield-demo';
const TOTP = '123456';
const ADMIN = 'w.kamau@harborpine.example';

// Whether the person who asked may decide their own request is the Approvals · decide cell of their role: the
// signed-in Builder's role lacks it, so the card offers no Approve until a workspace admin ticks the cell on the
// Builder role (Access › Roles). The page reloads after, so the session carries the change.
async function builderMayDecide() {
  const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
  const signIn = await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: ADMIN, password: PASSWORD }) });
  const headers = { Authorization: `Bearer ${(await signIn.json()).data.token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
  const list = (await (await fetch(`${platform}/v1/roles?q=Builder`, { headers })).json()).data;
  const builder = (list.data ?? list.items ?? list).find((r) => r.builtin && r.name === 'Builder');
  const detail = (await (await fetch(`${platform}/v1/roles/${builder.id}`, { headers })).json()).data;
  const permissions = [...detail.permissions.map(({ area, action, scope }) => ({ area, action, scope })), { area: 'approvals', action: 'decide', scope: 'all' }];
  return (await fetch(`${platform}/v1/roles/${builder.id}/permissions`, { method: 'PUT', headers, body: JSON.stringify({ permissions }) })).status;
}

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    // An approval card's decision goes to Reviews' route (components/chat/use-thread-actions.tsx), not the widget route.
    const decisions = [];
    page.on('response', (r) => {
      if (r.request().method() === 'POST' && /\/reviews\/[^/]+\/decision$/.test(r.url())) decisions.push(r.status());
    });

    await page.goto(`${consoleUrl}/chat?agent=ag_fraud`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const box = page.getByLabel('Message');
    await box.waitFor({ timeout: 120_000 });
    await box.fill('Place a 24-hour hold on wire W-88213');
    await page.getByRole('button', { name: 'Send' }).click();

    const approve = page.getByRole('button', { name: 'Approve', exact: true });
    // Non-vacuous: without the cell the server answers canDecide false for the asker, so the card offers no Approve.
    await page.getByTestId('approval-waiting-on').first().waitFor({ timeout: 60_000 });
    check('the Builder who asked, whose role lacks Approvals · decide, is offered no Approve', (await approve.count()) === 0);
    check('the workspace admin ticks Approvals · decide on the Builder role', (await builderMayDecide()) === 200);
    await page.reload({ waitUntil: 'domcontentloaded' });
    check('approval widget with an Approve button rendered', await approve.waitFor({ timeout: 60_000 }).then(() => true, () => false));
    check('widget names the wire', (await page.getByText('W-88213').count()) > 0);
    await approve.click();
    const confirmRun = page.getByRole('button', { name: 'Approve and run' });
    if (await confirmRun.waitFor({ timeout: 3_000 }).then(() => true, () => false)) await confirmRun.click();

    const dialog = page.getByRole('dialog', { name: 'Confirm it is you' });
    const shown = await dialog.waitFor({ timeout: 15_000 }).then(() => true, () => false);
    // Non-vacuous: the decision must not reach the API before step-up; a console that skipped it would post here.
    check('step-up dialog shown before the approval is sent', shown && decisions.length === 0, { shown, decisions });
    await page.locator('#reauth-secret').fill(PASSWORD);
    if (await page.locator('#reauth-code').count()) await page.locator('#reauth-code').fill(TOTP);
    await page.getByTestId('reauth-submit').click();

    const resumed = await page.getByText('The hold is in place.').waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check('one decision sent after step-up and accepted', decisions.length === 1 && decisions[0] === 200, decisions);
    check('the run resumed and the continuation shows in the thread', resumed);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
