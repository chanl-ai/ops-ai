// uc-100 the console matches the page plan, ui layer: docs/usecases/console/console-matches-page-plan.md. James on
// the mock-backed console: the Overview shows only what waits on a person, Agents has no Templates entry, Chat reaches
// Conversations from the sidebar, and the fourth role is called reviewer.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    // Overview: the Reviews count and the Cases "Needs a person" view; no performance tiles, chart or health table.
    await page.goto(`${consoleUrl}/`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByTestId('overview-reviews').waitFor({ timeout: 120_000 });
    const overview = {
      reviews: await page.getByTestId('overview-reviews').getByText('Waiting on review').count(),
      cases: await page.getByTestId('overview-cases').getByText('Needs a person').count(),
      tasks: await page.getByText('Agent tasks').count(),
      chart: await page.locator('.recharts-wrapper').count(),
      health: await page.getByText('Workflow health').count(),
    };
    check('the Overview shows the Reviews count and Needs a person, and no performance tiles, chart or health table', overview.reviews === 1 && overview.cases === 1 && overview.tasks === 0 && overview.chart === 0 && overview.health === 0, overview);
    await page.getByTestId('overview-cases').click();
    await page.waitForURL((u) => u.pathname === '/cases', { timeout: 30_000 });
    check('Needs a person opens Cases', new URL(page.url()).pathname === '/cases', page.url());

    // Agents: no Templates tab and no Start from template until templates have an API.
    await page.goto(`${consoleUrl}/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByTestId('create-agent-button').waitFor({ timeout: 120_000 });
    const agents = { templatesTab: await page.getByRole('tab', { name: 'Templates' }).count(), startFromTemplate: await page.getByRole('button', { name: 'Start from template' }).count() };
    check('Agents offers no Templates tab and no Start from template', agents.templatesTab === 0 && agents.startFromTemplate === 0, agents);

    // Chat reaches Conversations from the sidebar.
    const sidebar = page.locator('[data-sidebar="sidebar"]').first();
    const link = sidebar.getByRole('link', { name: 'Conversations' });
    const listed = await link.waitFor({ timeout: 30_000 }).then(() => true, () => false);
    if (listed) await link.click();
    await page.waitForURL((u) => u.pathname === '/chat/conversations', { timeout: 60_000 }).catch(() => undefined);
    check('Conversations is reached from Chat in the sidebar', listed && new URL(page.url()).pathname === '/chat/conversations', { listed, url: page.url() });

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
