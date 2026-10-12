// uc-040 Security decides a tool module review, ui layer: docs/usecases/tools-service/security-decides-a-module-review.md.
// Headless Chromium, three people signed in through platform-service: James requests, Maya (approver on Operations)
// cannot decide, Nadia (approver on Security) decides from the Reviews page's Tool modules tab.
import { PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platformUrl = `http://127.0.0.1:${PLATFORM_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const HOST = `statements-${TAG}.bank.example`;
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`${platformUrl}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
async function signIn(browser, consoleUrl, email) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}
async function openToolModulesTab(page, consoleUrl) {
  await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByRole('tab', { name: /^Tool modules/ }).or(page.getByRole('button', { name: /^Tool modules/ })).first().click({ timeout: 120_000 });
  return page.getByTestId('tool-module-reviews');
}

await withUiStack(
  async (consoleUrl) => {
    // James's module, with its first review requested (the request is his; the decision is Security's).
    const james = await tokenFor('j.richardson@northfieldbank.com');
    const J = as(james, 'team_ops');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: J, body: JSON.stringify({ value: HOST, note: 'uc-040 ui' }) });
    const made = await (await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Statements ${TAG}`, name: `uc040-ui-${TAG}`, type: 'http' }) })).json();
    const id = made.data.id;
    await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: `get_statement_${TAG}`, description: '', access: 'read', method: 'GET', url: `https://${HOST}/v1/x` }) });
    const reviewed = await (await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'First version' }) })).json();
    const rid = reviewed.data.reviews.find((r) => r.decision === 'pending').id;

    const browser = await chromium.launch();
    try {
      const errors = [];
      // James, on his module's Approval tab: the form is there and off, saying Security decides.
      const jp = await signIn(browser, consoleUrl, 'j.richardson@northfieldbank.com');
      jp.on('pageerror', (e) => errors.push(e.message));
      await jp.goto(`${consoleUrl}/tools/${id}?tab=approval`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const jform = jp.getByTestId('module-review-decision');
      await jform.waitFor({ timeout: 60_000 });
      check('the requester sees the decision form switched off: Security decides', (await jform.getByRole('button', { name: 'Security decides' }).isDisabled()) && (await jform.getByText(/You requested this review/).count()) === 1);

      // Maya, an approver on Operations: the Tool modules tab lists it, the form is off, and the service refuses her.
      const mp = await signIn(browser, consoleUrl, 'm.okafor@northfieldbank.com');
      mp.on('pageerror', (e) => errors.push(e.message));
      const mtab = await openToolModulesTab(mp, consoleUrl);
      const mrow = mtab.getByRole('row', { name: new RegExp(`Statements ${TAG}`) });
      const mListed = await mrow.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      await mrow.click().catch(() => undefined);
      const mform = mp.getByTestId('module-review-decision');
      await mform.waitFor({ timeout: 30_000 }).catch(() => undefined);
      const mOff = (await mform.getByRole('button', { name: 'Security decides' }).isDisabled().catch(() => false)) && (await mform.getByText(/Security team decides/).count()) === 1;
      const maya = await tokenFor('m.okafor@northfieldbank.com');
      const refused = await fetch(`${tools}/v1/tool-modules/${id}/reviews/${rid}/decide`, { method: 'POST', headers: as(maya, 'team_ops'), body: JSON.stringify({ decision: 'approved' }) });
      check('an approver on another team sees it listed, the form off, and the service refuses her (403)', mListed && mOff && refused.status === 403, { mListed, mOff, status: refused.status });

      // Nadia, Security's approver: a change request needs a reason; then she approves from the tab.
      const np = await signIn(browser, consoleUrl, 'n.petrov@northfieldbank.com');
      np.on('pageerror', (e) => errors.push(e.message));
      const ntab = await openToolModulesTab(np, consoleUrl);
      const nrow = ntab.getByRole('row', { name: new RegExp(`Statements ${TAG}`) });
      await nrow.waitFor({ timeout: 60_000 });
      await nrow.click();
      const nform = np.getByTestId('module-review-decision');
      await nform.waitFor({ timeout: 30_000 });
      let posted = 0;
      np.on('request', (r) => r.method() === 'POST' && r.url().endsWith(`/reviews/${rid}/decide`) && posted++);
      await nform.getByRole('button', { name: 'Request changes' }).click();
      const asked = await nform.getByText(/Say what has to change/).waitFor({ timeout: 10_000 }).then(() => true, () => false);
      check('requesting changes without a reason is stopped in the form and sends nothing', asked && posted === 0, { asked, posted });
      const decided = armed(np.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/reviews/${rid}/decide`), { timeout: 60_000 }));
      await nform.getByRole('button', { name: 'Approve and publish' }).click();
      const res = await decided;
      const after = res ? (await res.json()).data : undefined;
      check('Security approves from the Reviews tab and the module is published', res?.status() === 200 && after?.status === 'published', { status: res?.status(), state: after?.status });
      const gone = await nrow.waitFor({ state: 'detached', timeout: 30_000 }).then(() => true, () => false);
      check('the decided review leaves the Tool modules tab', gone);

      // Back on the module page: the decision and the published version show.
      await jp.goto(`${consoleUrl}/tools/${id}?tab=approval`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const shown = await jp.getByText(/Approved/).first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('the module page shows the review approved by Security and no decision form', shown && (await jp.getByTestId('module-review-decision').count()) === 0 && (await jp.getByText(/Nadia Petrov/).count()) > 0);

      // US4: the publish dialog says What changed is required. Stage a description edit to get Publish version.
      const ops = await (await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J })).json();
      await fetch(`${tools}/v1/tool-modules/${id}/operations/${ops.data.operations[0].id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ description: 'Monthly statement' }) });
      await jp.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await jp.getByRole('button', { name: 'Publish version' }).first().click({ timeout: 60_000 });
      const dialog = jp.getByRole('dialog', { name: /Publish a (minor|major) version\?/ });
      await dialog.waitFor({ timeout: 30_000 });
      check('the publish dialog says What changed is required and Publish waits for it', (await dialog.getByText('Required. Workflows and reviewers read it.').count()) === 1 && (await dialog.getByRole('button', { name: 'Publish', exact: true }).isDisabled()));

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
