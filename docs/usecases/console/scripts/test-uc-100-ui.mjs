// uc-100 the console matches the page plan, ui layer: docs/usecases/console/console-matches-page-plan.md. James on
// the mock-backed console: the Overview shows only what waits on a person, Agents has no Templates entry, Chat reaches
// All chats from the sidebar, and the fourth role is called reviewer.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    // Each part reports its own failure, so one stale part cannot hide the others.
    try {
      // Overview: the Reviews count and the Cases "Needs a person" view; no performance tiles, chart or health table.
      await page.goto(`${consoleUrl}/`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByText('Human Tasks waiting for you').waitFor({ timeout: 120_000 });
      const overview = {
        reviews: await page.getByText(/^Human Tasks waiting for you/).count(),
        cases: await page.getByText(/^Cases due/).count(),
        tasks: await page.getByText('Agent tasks').count(),
        chart: await page.locator('.recharts-wrapper').count(),
        health: await page.getByText('Workflow health').count(),
      };
      check('the Overview shows the Human Tasks waiting and Cases due, and no performance tiles, chart or health table', overview.reviews === 1 && overview.cases === 1 && overview.tasks === 0 && overview.chart === 0 && overview.health === 0, overview);
      await page.locator('a[href="/cases"]', { hasText: 'Open all' }).click();
      await page.waitForURL((u) => u.pathname === '/cases', { timeout: 30_000 });
      check('Open all on Cases due opens Cases', new URL(page.url()).pathname === '/cases', page.url());
    } catch (e) {
      check('the Overview shows the Human Tasks waiting and Cases due, and no performance tiles, chart or health table', false, String(e).slice(0, 300));
    }

    try {
      // Agents: no Templates tab and no Start from template until templates have an API.
      await page.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('create-agent-button').waitFor({ timeout: 120_000 });
      const agents = { templatesTab: await page.getByRole('tab', { name: 'Templates' }).count(), startFromTemplate: await page.getByRole('button', { name: 'Start from template' }).count() };
      check('Agents offers no Templates tab and no Start from template', agents.templatesTab === 0 && agents.startFromTemplate === 0, agents);
    } catch (e) {
      check('Agents offers no Templates tab and no Start from template', false, String(e).slice(0, 300));
    }

    // Chat reaches All chats from the sidebar, which lists the Work area only (no Agents row beside it).
    // New chat has no area of its own and shows the one last used (Build, from Agents), so Work is picked before the sidebar is read.
    await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('group', { name: 'Area' }).getByText('Work', { exact: true }).click({ timeout: 30_000 }).catch(() => undefined);
    const sidebar = page.locator('[data-sidebar="sidebar"]').first();
    const link = sidebar.getByRole('link', { name: 'All chats' });
    const listed = await link.waitFor({ timeout: 30_000 }).then(() => true, () => false);
    const alsoAgents = await sidebar.getByRole('link', { name: 'Agents', exact: true }).count();
    if (listed) await link.click();
    await page.waitForURL((u) => u.pathname === '/chat/conversations', { timeout: 60_000 }).catch(() => undefined);
    check('All chats is reached from Chat in the sidebar, which lists one area', listed && alsoAgents === 0 && new URL(page.url()).pathname === '/chat/conversations', { listed, alsoAgents, url: page.url() });

    // The fourth role is a reviewer: the members' role filter and badges say Reviewer, never Approver.
    await page.goto(`${consoleUrl}/settings/members`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('table').first().waitFor({ timeout: 120_000 });
    const names = { reviewer: await page.getByRole('table').getByText('Reviewer', { exact: true }).count(), approver: await page.getByText('Approver', { exact: true }).count() };
    check('members are called reviewers, not approvers', names.reviewer > 0 && names.approver === 0, names);

    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
