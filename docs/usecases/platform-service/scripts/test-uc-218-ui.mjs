// uc-218 a person invited as a reviewer, ui layer: docs/usecases/platform-service/role-reviewer.md. A builder's
// publish request opens with the decision form, Approve publishes it, and the agent page says View only.
import { AGENTS_PORT, INVITED_PASSWORD, check, chromium, consoleSignIn, finish, invitePerson, withUiStack } from '@ops-ai/usecase-runner/harness';

const TAG = Math.random().toString(36).slice(2, 7);
const agents = `http://127.0.0.1:${AGENTS_PORT}`;

await withUiStack(
  async (consoleUrl) => {
    const builder = await invitePerson('p.shah@northfieldbank.com', `builder.${TAG}@northfieldbank.com`, 'builder');
    await invitePerson('p.shah@northfieldbank.com', `reviewer.${TAG}@northfieldbank.com`, 'approver');
    const H = { Authorization: `Bearer ${builder}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const agent = (await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: H, body: JSON.stringify({ name: `Desk ${TAG}`, role: 'Answers' }) })).json()).data;
    const request = (await (await fetch(`${agents}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: H, body: JSON.stringify({ version: agent.version }) })).json()).data;
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, `reviewer.${TAG}@northfieldbank.com`, INVITED_PASSWORD, errors);
      await page.goto(`${consoleUrl}/reviews?review=${request.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const dialog = page.getByRole('dialog').first();
      await dialog.waitFor({ timeout: 120_000 });
      const approve = dialog.getByRole('button', { name: /^Approve/ });
      const offered = await approve.first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('the reviewer gets the decision form on the pending request', offered);
      if (offered) await approve.first().click();
      const decided = await (async () => {
        for (let i = 0; i < 30; i++) {
          const r = await (await fetch(`${agents}/v1/publish-requests/${request.id}`, { headers: H })).json();
          if (r.data?.status !== 'pending') return r.data?.status;
          await new Promise((s) => setTimeout(s, 500));
        }
        return 'pending';
      })();
      check('Approve publishes the agent', decided === 'approved', decided);
      await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      check('the agent page tells the reviewer View only', await page.getByTestId('read-only-notice').waitFor({ timeout: 90_000 }).then(() => true, () => false));
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, agentsEnv: { OPS_REGISTRY_AUTO_APPROVE: 'false' } },
);
finish();
