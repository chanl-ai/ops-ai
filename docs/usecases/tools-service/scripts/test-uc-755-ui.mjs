// uc-755, ui layer: docs/usecases/tools-service/a-team-holding-only-a-workflow.md. A plain builder of a second team
// ("Desk"), added by invite-and-accept, opens the owner's bank module through Desk's workflow grant. The module page shows
// the operations but no control that edits, publishes, requests a review or deletes it, and a direct edit through
// the page's own API call is refused 404. Platform sign-in, the fake bank on https; no model call.
import { PLATFORM_PORT, TOOLS_PORT, AGENTS_PORT, approveToolReview, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, as, until } from '../../lib/workflow_ui.mjs';

const NADIA = 'n.petrov@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const WANJIRU = 'w.kamau@harborpine.example';
const PRIYA = 'p.shah@harborpine.example';
const MEMBER_PASSWORD = "an invited person's password";
const RUN = Math.random().toString(36).slice(2, 7);
const READ = `get_account_${RUN}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const call = async (method, url, headers, body) => {
  const r = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  return { status: r.status, data: (await r.json().catch(() => ({}))).data, text: r.ok ? '' : await r.text().catch(() => '') };
};

await withUiStack(
  async (consoleUrl, stack) => {
    const S = await as(SAM, 'team_security');
    await call('POST', `${tools}/v1/egress/hosts`, S, { value: stack.bank.host, note: 'uc-755' });
    await call('POST', `${tools}/v1/egress/ranges`, S, { value: stack.bank.range, note: 'uc-755' });
    const J = await as(JAMES);
    const made = await call('POST', `${tools}/v1/tool-modules/blank`, J, { displayName: `Accounts ${RUN}`, name: `accounts-${RUN}`, type: 'http' });
    const moduleId = made.data?.id;
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/operations`, J, { name: READ, description: 'Read an account', access: 'read', method: 'GET', url: `https://${stack.bank.host}/v1/accounts/{accountId}` });
    await call('POST', `${tools}/v1/tool-modules/${moduleId}/reviews`, J, { note: 'uc-755' });
    await approveToolReview(moduleId, await as(NADIA, 'team_security'), J);

    // The second team, and a plain builder added by invite-and-accept, never the team's creator.
    const W = await as(WANJIRU, 'team_platform');
    const team = await call('POST', `${platform}/v1/settings/teams`, W, { name: `Desk ${RUN}`, admin: PRIYA });
    const desk = team.data?.id;
    const email = `desk.${RUN}@harborpine.example`;
    const invite = await call('POST', `${platform}/v1/settings/members/invite`, await as(PRIYA, desk), { emails: [email], role: 'builder' });
    const token = invite.data?.invites?.[0]?.token;
    const accepted = await call('POST', `${platform}/v1/invites/${token}/accept`, { 'Content-Type': 'application/json' }, { name: 'Desk Builder', password: MEMBER_PASSWORD });
    check('setup: Desk is made and a builder joins it by invitation', team.status === 201 && accepted.status === 200, { team: team.status, accepted: accepted.status });
    const signed = await call('POST', `${platform}/v1/auth/sign-in`, { 'Content-Type': 'application/json' }, { email, password: MEMBER_PASSWORD });
    const D = { Authorization: `Bearer ${signed.data?.token}`, 'X-Team-Id': desk, 'Content-Type': 'application/json' };
    const flow = await call('POST', `${agents}/v1/workflows`, D, { name: `Desk intake ${RUN}`, trigger: 'manual' });
    await new Promise((r) => setTimeout(r, 31_000)); // past tools-service's 30 s workflow list cache
    // Making a team changes permissions, which refuses tokens issued before it: James and Maya sign in again.
    const J2 = await as(JAMES);
    const asked = await call('POST', `${tools}/v1/tool-modules/${moduleId}/approvals`, J2, { workflowId: flow.data?.id, environment: 'production', operations: [READ], expiresInDays: 30, justification: 'Desk intake reads accounts' });
    const decided = await call('POST', `${tools}/v1/tool-modules/${moduleId}/approvals/${asked.data?.id}/decide`, await as(MAYA), { decision: 'approved' });
    check('setup: the owner approves Desk\'s workflow for the read', asked.status === 201 && decided.status === 200, { asked: asked.status, decided: decided.status });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, email, MEMBER_PASSWORD, errors);
      await page.goto(`${consoleUrl}/data/tools/${moduleId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // Non-vacuous: the grant is real, so the page shows the operation; the missing controls are the grant's limit.
      const shown = await page.getByText(READ).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('1 Desk\'s builder opens the module and sees its operation', shown, { url: page.url() });
      const controls = {
        addOperation: await page.getByTestId('ops-add').count(),
        importOperations: await page.getByTestId('ops-import').count(),
        requestReview: await page.getByTestId('header-request-review').count(),
      };
      check('2 there is no Add operation, Import or Request security review control', Object.values(controls).every((n) => n === 0), controls);
      await page.getByRole('button', { name: /^Actions/ }).click().catch(() => undefined);
      const menu = {
        editDetails: await page.getByTestId('edit-details').count(),
        deleteEnabled: await page.getByRole('menuitem', { name: /^Delete/ }).and(page.locator(':not([data-disabled])')).count(),
      };
      check('3 the Actions menu offers neither Edit details nor a Delete that works', menu.editDetails === 0 && menu.deleteEnabled === 0, menu);
      await page.keyboard.press('Escape');
      const publish = await page.getByRole('button', { name: /^Publish version/ }).filter({ visible: true }).count();
      check('4 no Publish version button is visible', publish === 0, { publish });
      const edit = await call('PATCH', `${tools}/v1/tool-modules/${moduleId}`, D, { description: 'changed by Desk' });
      check('5 the same edit sent directly is refused 404', edit.status === 404, { status: edit.status });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: true, gateway: true } },
);

finish();
