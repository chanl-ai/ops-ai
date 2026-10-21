// uc-040 Security decides a tool module review, ui layer: docs/usecases/tools-service/security-decides-a-module-review.md.
// Headless Chromium, three people signed in through platform-service: James requests, Maya (approver on Operations)
// cannot decide, Nadia (approver on Security) decides it in Human Tasks, where every review is decided (c-163).
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
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
async function openReview(page, consoleUrl, rid) {
  await page.goto(`${consoleUrl}/reviews?review=${rid}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const approve = page.getByRole('button', { name: /^(Approve and publish|Another publisher approves)$/ });
  return approve.first().waitFor({ timeout: 120_000 }).then(() => true, () => false);
}

await withUiStack(
  async (consoleUrl) => {
    // James's module, with its first review requested (the request is his; the decision is Security's).
    const james = await tokenFor('j.richardson@harborpine.example');
    const J = as(james, 'team_ops');
    // Egress is the Security team's admins' to change, so Sam allows the host.
    const S = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
    const allowed = await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: HOST, note: 'uc-040 ui' }) });
    check("Security's admin allows the module's host for egress", allowed.ok, { status: allowed.status });
    const made = await (await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Statements ${TAG}`, name: `uc040-ui-${TAG}`, type: 'http' }) })).json();
    const id = made.data.id;
    await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: `get_statement_${TAG}`, description: '', access: 'read', method: 'GET', url: `https://${HOST}/v1/x` }) });
    const reviewed = await (await fetch(`${tools}/v1/tool-modules/${id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'First version' }) })).json();
    const rid = reviewed.data.versions.find((v) => v.status === 'in_review')?.reviewId;
    check('the review opens as a publish request in Reviews', String(rid).startsWith('TMP-'), { rid });

    const browser = await chromium.launch();
    try {
      const errors = [];
      // James, on his module's Approval tab: it waits for Security, with a link to Human Tasks and no decide form.
      const jp = await signIn(browser, consoleUrl, 'j.richardson@harborpine.example');
      jp.on('pageerror', (e) => errors.push(e.message));
      await jp.goto(`${consoleUrl}/tools/${id}?tab=approval`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const link = jp.getByRole('link', { name: 'Open in Human Tasks' });
      const linked = await link.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('the module page links the waiting review to Human Tasks and has no decide form', linked && (await link.getAttribute('href')) === `/reviews?review=${rid}` && (await jp.getByTestId('module-review-decision').count()) === 0);

      // Maya, an approver on Operations: Human Tasks offers her no approval on Security's review, and Reviews refuses
      // her decision.
      const mp = await signIn(browser, consoleUrl, 'm.okafor@harborpine.example');
      mp.on('pageerror', (e) => errors.push(e.message));
      const offered = await openReview(mp, consoleUrl, rid);
      const maya = await tokenFor('m.okafor@harborpine.example');
      const refused = await fetch(`${agents}/v1/publish-requests/${rid}/decision`, { method: 'POST', headers: as(maya, 'team_ops'), body: JSON.stringify({ decision: 'approved' }) });
      check('an approver on another team is offered no approval and Reviews refuses her (403)', !offered && refused.status === 403, { offered, status: refused.status });

      // Nadia, Security's approver: returning it needs a reason; then she approves it in Human Tasks.
      const np = await signIn(browser, consoleUrl, 'n.petrov@harborpine.example');
      np.on('pageerror', (e) => errors.push(e.message));
      check('Security opens the review in Human Tasks', await openReview(np, consoleUrl, rid));
      let posted = 0;
      np.on('request', (r) => r.method() === 'POST' && r.url().endsWith(`/reviews/${rid}/decision`) && posted++);
      await np.getByRole('button', { name: 'Return to requester' }).click();
      const asked = await np.getByText(/Add a reason/).first().waitFor({ timeout: 10_000 }).then(() => true, () => false);
      check('returning it without a reason is stopped in the form and sends nothing', asked && posted === 0, { asked, posted });
      const decided = armed(np.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/reviews/${rid}/decision`), { timeout: 60_000 }));
      await np.getByRole('button', { name: 'Approve and publish' }).click();
      const res = await decided;
      const after = (await (await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J })).json()).data;
      check('Security approves in Human Tasks and the module is published', res?.status() === 200 && after?.status === 'published', { status: res?.status(), state: after?.status });

      // Back on the module page: the decision and the published version show.
      await jp.goto(`${consoleUrl}/tools/${id}?tab=approval`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const shown = await jp.getByText(/Approved/).first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('the module page shows the review approved by Security', shown && (await jp.getByText(/Nadia Petrov|n\.petrov@/).count()) > 0);

      // US4: the publish dialog says What changed is required. Stage a description edit to get Publish version.
      const ops = await (await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J })).json();
      await fetch(`${tools}/v1/tool-modules/${id}/operations/${ops.data.operations[0].id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ description: 'Monthly statement' }) });
      await jp.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await jp.getByRole('button', { name: 'Publish version' }).first().click({ timeout: 60_000 });
      const dialog = jp.getByRole('dialog', { name: /Publish a (minor|major) version\?/ });
      await dialog.waitFor({ timeout: 30_000 });
      check('the publish dialog says What changed is required and Publish waits for it', (await dialog.getByText('Required. Workflows and reviewers read it.').count()) === 1 && (await dialog.getByRole('button', { name: 'Publish', exact: true }).isDisabled()));

      // Egress and secrets are the Security team's admins' to change: James (a builder) and Nadia (Security's approver)
      // read them with no controls; Sam (Security's admin) gets Add host and Add secret.
      const controls = async (page) => {
        await page.goto(`${consoleUrl}/settings/egress`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('heading', { name: 'Egress' }).first().waitFor({ timeout: 60_000 });
        await page.getByText(HOST).first().waitFor({ timeout: 60_000 }).catch(() => undefined);
        const egress = await page.getByRole('button', { name: 'Add host' }).count();
        await page.goto(`${consoleUrl}/settings/secrets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('heading', { name: 'Secrets' }).first().waitFor({ timeout: 60_000 });
        await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => undefined);
        const secrets = await page.getByRole('button', { name: 'Add secret' }).count();
        return { egress, secrets };
      };
      const asJames = await controls(jp);
      const asNadia = await controls(np);
      check('a builder and a Security approver see egress and secrets with no add controls', asJames.egress + asJames.secrets + asNadia.egress + asNadia.secrets === 0, { asJames, asNadia });
      const sp = await signIn(browser, consoleUrl, 's.adeyemi@harborpine.example');
      sp.on('pageerror', (e) => errors.push(`sam: ${e.message}`));
      const asSam = await controls(sp);
      check("Security's admin sees Add host and Add secret", asSam.egress === 1 && asSam.secrets === 1, asSam);

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
