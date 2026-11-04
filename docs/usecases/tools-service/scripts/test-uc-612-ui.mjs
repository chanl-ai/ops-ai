// uc-612 an install turns a feature on or off from its config, ui layer:
// docs/usecases/tools-service/an-install-turns-a-feature-on.md. Priya signs in to a console on platform sign-in twice:
// on an install with no flags, nothing offers the MCP address or connecting an outside assistant; on one whose
// OPS_FLAGS names mcp_gateway, the same places show it. The flag reaches platform-service and tools-service from this
// process's environment, as the install config reaches them.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD, PRIYA } from '../../lib/workflow_ui.mjs';

/** Opens ⌘K, searches, and returns the option labels it lists. */
async function palette(page, query) {
  await page.keyboard.press('Meta+k');
  const input = page.getByRole('combobox').or(page.getByPlaceholder(/search/i)).first();
  await input.waitFor({ timeout: 30_000 });
  await input.fill(query);
  await page.waitForTimeout(800);
  const labels = await page.getByRole('option').allInnerTexts();
  await page.keyboard.press('Escape');
  return labels.join(' | ');
}

/** What each place shows about the MCP address, for one install. */
async function walk(consoleUrl, step) {
  const browser = await chromium.launch();
  const errors = [];
  const seen = {};
  try {
    const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
    await page.goto(`${consoleUrl}/channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByTestId('channel-gallery').waitFor({ timeout: 90_000 });
    seen.palette = await palette(page, 'mcp');
    seen.tab = await page.getByTestId('channel-tab-mcp').count();
    seen.card = await page.getByTestId('gallery-mcp').count();
    await page.getByTestId('connect-channel').click();
    seen.soon = (await page.getByText(/coming soon/).first().innerText()).trim();
    await page.keyboard.press('Escape');
    await page.goto(`${consoleUrl}/channels/mcp`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByText('This page could not be found').or(page.getByTestId('channel-tab-mcp')).first().waitFor({ timeout: 90_000 });
    seen.notFound = await page.getByText('This page could not be found').count();
    await page.goto(`${consoleUrl}/tools/custom`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('tab', { name: /^Workflows/ }).or(page.getByRole('button', { name: /^Workflows/ })).first().click({ timeout: 90_000 });
    await page.getByTestId('workflow-tools').waitFor({ timeout: 60_000 });
    seen.toolsLink = await page.getByTestId('workflow-tools-manage').count();
    await page.screenshot({ path: `${process.env.OPS_EVIDENCE_DIR ?? '/tmp'}/uc-612-${step}-tools.png` });
  } finally {
    await browser.close();
  }
  return { seen, errors };
}

delete process.env.OPS_FLAGS;
const off = await withUiStack((url) => walk(url, 'off'), { platform: true, tools: {} });
check('1 with no flags, ⌘K offers neither Connect your assistant nor Copy MCP URL', !/Connect your assistant|Copy MCP URL/.test(off.seen.palette), off.seen.palette);
check('1 with no flags, Channels has no MCP tab or card', off.seen.tab === 0 && off.seen.card === 0, off.seen);
check('1 with no flags, the Connect channel menu does not name MCP as coming soon', !/MCP/.test(off.seen.soon), off.seen.soon);
check('1 with no flags, /channels/mcp is not found', off.seen.notFound === 1, off.seen);
check('1 with no flags, Tools does not link to the MCP tab', off.seen.toolsLink === 0, off.seen);
check('1 no page error', off.errors.length === 0, off.errors);

process.env.OPS_FLAGS = 'mcp_gateway';
const on = await withUiStack((url) => walk(url, 'on'), { platform: true, tools: {} });
check('2 with mcp_gateway on, ⌘K offers Connect your assistant and Copy MCP URL', /Connect your assistant/.test(on.seen.palette) && /Copy MCP URL/.test(on.seen.palette), on.seen.palette);
check('2 with mcp_gateway on, Channels has the MCP tab and card', on.seen.tab === 1 && on.seen.card === 1, on.seen);
check('2 with mcp_gateway on, /channels/mcp opens the MCP channel', on.seen.notFound === 0, on.seen);
check('2 with mcp_gateway on, Tools links to the MCP tab', on.seen.toolsLink === 1, on.seen);
check('2 no page error', on.errors.length === 0, on.errors);

finish();
