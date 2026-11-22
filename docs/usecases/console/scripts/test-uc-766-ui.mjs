// uc-766 a role given to a group opens the approvals cell for its members, ui layer:
// docs/usecases/console/role-for-a-group-and-approvals.md. Signed in through platform-service: Wanjiru (workspace
// admin) makes a role holding the approvals cells and its page shows them; Ravi (viewer) reads Approvals with its
// switches off until his group is given the role, then can change them. No route or screen gives a role to a group, so
// the group and its role are seeded by lib/group_role.py.
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';
import { pgUrl } from '../../../../packages/usecase-runner/src/isolation.ts';
import { PASSWORD, as } from '../../lib/workflow_ui.mjs';

const TAG = Math.random().toString(36).slice(2, 6);
const WANJIRU = 'w.kamau@harborpine.example';
const RAVI = 'r.menon@harborpine.example';
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const SWITCH = 'Ask before an agent changes anything in an app';

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl) => {
    const W = await as(WANJIRU);
    const me = async (headers) => (await (await fetch(`${platform}/v1/me`, { headers })).json()).data;
    const admin = await me(W);
    const viewer = await me(await as(RAVI));
    const made = await (
      await fetch(`${platform}/v1/roles`, {
        method: 'POST',
        headers: W,
        body: JSON.stringify({ name: `Approval desk ${TAG}`, description: 'Sets the team approval rules', permissions: [{ area: 'approvals', action: 'view', scope: 'all' }, { area: 'approvals', action: 'manage', scope: 'all' }] }),
      })
    ).json();
    const role = made.data;
    if (!role?.id) throw new Error(`setup: the role was not made: ${JSON.stringify(made).slice(0, 300)}`);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const approvals = async (page) => {
        await page.goto(`${consoleUrl}/settings/approvals`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const toggle = page.getByRole('switch', { name: SWITCH });
        await toggle.waitFor({ timeout: 120_000 });
        return toggle;
      };

      await step('1 the role page shows the approvals cells it holds', async () => {
        const page = await consoleSignIn(browser, consoleUrl, WANJIRU, PASSWORD, errors);
        await page.goto(`${consoleUrl}/govern/access/roles/${role.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('cell-approvals-manage').waitFor({ timeout: 120_000 });
        const cells = { view: await page.getByTestId('cell-approvals-view').count(), manage: await page.getByTestId('cell-approvals-manage').count(), decide: await page.getByTestId('cell-approvals-decide').count() };
        const held = (await page.getByText(/held by \d+/).first().innerText()).trim();
        await shootBothWidths(page, 'console', 'uc-766-role-approvals', async () => page.waitForTimeout(300));
        check('1 the role page shows the approvals cells it holds', cells.view > 0 && cells.manage > 0 && /held by 0$/.test(held), { cells, held });
        await page.context().close();
      });

      let viewerPage;
      await step('2 a viewer reads Approvals with the switch off', async () => {
        viewerPage = await consoleSignIn(browser, consoleUrl, RAVI, PASSWORD, errors);
        const toggle = await approvals(viewerPage);
        check('2 a viewer reads Approvals with the switch off', await toggle.isDisabled(), { disabled: await toggle.isDisabled() });
        await viewerPage.context().close();
      });

      await step('3 the role is given to a group holding the viewer', async () => {
        const out = execFileSync('uv', ['run', 'python', join(ROOT, 'docs/usecases/lib/group_role.py'), pgUrl(process.env.OPS_USECASE_DB ?? 'ops_usecase'), admin.tenantId, admin.user.id, viewer.user.id, role.id, 'team_ops', `Case desk ${TAG}`], { cwd: join(ROOT, 'services/platform-service'), encoding: 'utf8' }).trim();
        const page = await consoleSignIn(browser, consoleUrl, WANJIRU, PASSWORD, errors);
        await page.goto(`${consoleUrl}/govern/access/roles/${role.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByText(/held by \d+/).first().waitFor({ timeout: 120_000 });
        const held = (await page.getByText(/held by \d+/).first().innerText()).trim();
        check('3 the role is given to a group holding the viewer', /^[\w-]+$/.test(out) && /held by 1$/.test(held), { group: out, held });
        await page.context().close();
      });

      await step('4 the viewer, signed in again, can change Approvals through the group', async () => {
        const page = await consoleSignIn(browser, consoleUrl, RAVI, PASSWORD, errors);
        const toggle = await approvals(page);
        await shootBothWidths(page, 'console', 'uc-766-approvals-for-group-member', async () => page.waitForTimeout(300));
        check('4 the viewer, signed in again, can change Approvals through the group', await toggle.isEnabled(), { enabled: await toggle.isEnabled() });
        await page.context().close();
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
