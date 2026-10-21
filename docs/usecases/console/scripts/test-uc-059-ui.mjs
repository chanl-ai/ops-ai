// uc-059 a builder sets a write's approval policy on the module page, ui layer: docs/usecases/console/write-approval-policy.md.
// Signed in through platform-service. James adds a write to a draft module, opens it in the operation sheet, asks for
// two approvers and lets the person who asked approve; the change reaches tools-service and shows on the operation.
import { PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const HOST = 'holds.bank.test';
const OP = `place_hold_${TAG}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

await withUiStack(
  async (consoleUrl) => {
    // Egress is changed only by an admin of the Security team (c-079).
    const P = { ...as(await tokenFor('s.adeyemi@harborpine.example')), 'X-Team-Id': 'team_security' };
    const J = as(await tokenFor('j.richardson@harborpine.example'));
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: P, body: JSON.stringify({ value: HOST, note: 'uc-059 ui' }) });
    const id = (await json(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Holds ${TAG}`, name: `uc059-holds-${TAG}`, type: 'http' }) }))).id;
    await json(await fetch(`${tools}/v1/tool-modules/${id}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: OP, description: 'Place a hold', access: 'write', method: 'POST', url: `https://${HOST}/v1/holds`, headers: [] }) }));

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = page.getByRole('row', { name: new RegExp(OP) });
      await row.waitFor({ timeout: 120_000 });
      const before = await row.getByText('Two approvals').count();

      // The row opens the operation's workbench (c-088); its access and approval policy is in the sheet it opens.
      await row.click();
      await page.getByTestId('workbench-policy').click({ timeout: 60_000 });
      const policy = page.getByTestId('op-approval-policy');
      await policy.waitFor({ timeout: 30_000 });
      const policyBefore = await policy.innerText();
      // The approving team defaults to the module's team; the sheet names it from the person's teams, so a name here
      // (not an id) shows platform-service and tools-service agree on team ids.
      check('the write shows its approving team by name and one approver', before === 0 && policyBefore === 'Approved by Operations', { before, policyBefore });

      await page.getByLabel('Approvals per call').click();
      await page.getByRole('option', { name: 'Two different people' }).click();
      // Whether the asker may approve is the tenant's requesterMayDecide policy (c-186): the sheet offers no switch.
      const selfSwitch = await page.getByRole('switch', { name: 'The person who asked may approve' }).count();
      const staged = armed(page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().includes(`/v1/tool-modules/${id}/operations/`), { timeout: 60_000 }));
      await page.getByTestId('op-stage').click();
      const res = await staged;
      const sent = res ? JSON.parse(res.request().postData() ?? '{}') : {};
      const op = res ? (await res.json()).data?.operations?.find((o) => o.name === OP) : undefined;
      check('Stage change sends two approvers and tools-service keeps them; no self-approval switch or field', res?.status() === 200 && sent.approvers === 2 && !('selfApproval' in sent) && !('approverTeam' in sent) && op?.approvers === 2 && !('selfApproval' in (op ?? {})) && op?.requiresApproval === true && selfSwitch === 0, { status: res?.status(), sent, selfSwitch, op: op && { approvers: op.approvers, requiresApproval: op.requiresApproval } });

      const policyAfter = await policy.innerText();
      await page.keyboard.press('Escape');
      await page.goto(`${consoleUrl}/tools/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await row.getByText('Two approvals').waitFor({ timeout: 30_000 }).catch(() => undefined);
      const rowAfter = await row.getByText('Two approvals').count();
      check('the operation shows two approvers in its row and its approving team in its sheet', rowAfter === 1 && policyAfter === 'Approved by Operations', { rowAfter, policyAfter });

      const live = (await json(await fetch(`${tools}/v1/tool-modules/${id}`, { headers: J }))).operations.find((o) => o.name === OP);
      check('a fresh read of the module returns the policy', live?.approvers === 2 && live?.approverTeam === 'team_ops' && !('selfApproval' in (live ?? {})), { approvers: live?.approvers, approverTeam: live?.approverTeam });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
