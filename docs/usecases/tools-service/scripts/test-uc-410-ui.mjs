// uc-410 an assistant uses a team's tools over MCP, ui layer: docs/usecases/tools-service/mcp-server.md, step 6.
// A link's Calls tab is read with mcp.view: Ravi (viewer) opens a link Priya made and sees the calls he made himself,
// none here, instead of being told his role cannot see them; Priya (admin) opens the same tab.
import { TOOLS_PORT, asRole, check, chromium, consoleSignIn, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD, PRIYA } from '../../lib/workflow_ui.mjs';

const RAVI = 'r.menon@harborpine.example';

/** What one person's Calls tab shows: the call list, or the access refusal. */
async function callsTab(browser, consoleUrl, email, linkId, errors, shoot) {
  const page = await consoleSignIn(browser, consoleUrl, email, PASSWORD, errors);
  await page.goto(`${consoleUrl}/build/channels/mcp/${linkId}?tab=calls`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('mcp-link-calls').or(page.getByTestId('query-forbidden')).first().waitFor({ timeout: 90_000 });
  const seen = { list: await page.getByTestId('mcp-link-calls').count(), refused: await page.getByTestId('query-forbidden').count(), empty: await page.getByText(/No calls/).count() };
  if (shoot) await shootBothWidths(page, 'tools-service', 'uc-410-calls-viewer', async () => page.waitForTimeout(400));
  await page.close();
  return seen;
}

process.env.OPS_FLAGS = 'mcp_gateway';
const out = await withUiStack(async (consoleUrl) => {
  const priya = await asRole('admin', 'team_ops');
  const made = await fetch(`http://127.0.0.1:${TOOLS_PORT}/v1/mcp-links`, {
    method: 'POST',
    headers: priya,
    body: JSON.stringify({ name: 'uc410 intake', tools: [{ id: 'workflow:wf_uc410', label: 'Claims intake' }] }),
  });
  const link = made.status === 201 ? (await made.json()).data : null;
  check('6 Priya makes a link (201)', !!link, made.status);
  const browser = await chromium.launch();
  const errors = [];
  try {
    const ravi = await callsTab(browser, consoleUrl, RAVI, link?.id, errors, true);
    const admin = await callsTab(browser, consoleUrl, PRIYA, link?.id, errors, false);
    return { ravi, admin, errors };
  } finally {
    await browser.close();
  }
}, { platform: true, tools: {} });

check('6 Ravi (viewer) sees the link\'s Calls tab with his own calls, none, and no access refusal', out.ravi.list === 1 && out.ravi.refused === 0 && out.ravi.empty >= 1, out.ravi);
check('6 Priya (admin) sees the link\'s Calls tab', out.admin.list === 1 && out.admin.refused === 0, out.admin);
check('6 no page error', out.errors.length === 0, out.errors);
finish();
