// uc-217 a person invited as a builder, ui layer: docs/usecases/platform-service/role-builder.md. Signed in, an agent
// page is editable with no View only and Access offers no Invite; on the pending review a viewer of the team sees who
// decides and no Approve (builders decide their team's reviews since D59).
import { AGENTS_PORT, INVITED_PASSWORD, check, chromium, consoleSignIn, finish, invitePerson, withUiStack } from '@ops-ai/usecase-runner/harness';

const EMAIL = `builder.${Math.random().toString(36).slice(2, 7)}@harborpine.example`;
const VIEWER = `viewer.${Math.random().toString(36).slice(2, 7)}@harborpine.example`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;

await withUiStack(
  async (consoleUrl) => {
    // The viewer first: each invitation changes the workspace's permissions, which refuses tokens issued before it.
    await invitePerson('p.shah@harborpine.example', VIEWER, 'viewer');
    const token = await invitePerson('p.shah@harborpine.example', EMAIL, 'builder');
    const H = { Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const agent = (await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: H, body: JSON.stringify({ name: `Desk ${Date.now() % 10000}`, role: 'Answers' }) })).json()).data;
    const request = (await (await fetch(`${agents}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: H, body: JSON.stringify({ version: agent.version }) })).json()).data;
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, EMAIL, INVITED_PASSWORD, errors);
      await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByText(agent.name).first().waitFor({ timeout: 90_000 });
      await page.waitForTimeout(2000);
      check('the builder edits their agent with no View only', (await page.getByTestId('read-only-notice').count()) === 0 && (await page.getByLabel('Name').first().isEditable()));
      await page.goto(`${consoleUrl}/access`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('row', { name: /Priya Shah/ }).waitFor({ timeout: 60_000 });
      check('Access offers the builder no Invite', (await page.getByTestId('access-invite').count()) === 0);
      const viewer = await consoleSignIn(browser, consoleUrl, VIEWER, INVITED_PASSWORD, errors);
      await viewer.goto(`${consoleUrl}/reviews?review=${request.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // Human Tasks opens the task beside the queue; its decision panel names who decides.
      await viewer.getByTestId('review-decided-by').first().waitFor({ timeout: 120_000 });
      await viewer.waitForTimeout(1500);
      const approve = await viewer.getByRole('button', { name: /^Approve/ }).count();
      check('on the pending review a viewer sees who decides and no Approve', request.status === 'pending' && approve === 0 && (await viewer.getByTestId('review-decided-by').count()) === 1, { status: request.status, approve });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, agentsEnv: { OPS_REGISTRY_AUTO_APPROVE: 'false' } },
);
finish();
