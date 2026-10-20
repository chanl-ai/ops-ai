// uc-015 tool module details page, ui layer: docs/usecases/tools-service/tool-module-details-page.md. Headless
// Chromium against the console; tool modules come from the mock until tools-service serves /v1/tool-modules.
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const MODULE = 'mod_core_banking';

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));

    // An operation is tested on its own workbench page (c-088): the module page has no side panel, and a row opens it.
    await page.goto(`${consoleUrl}/tools/${MODULE}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const row = page.getByRole('row', { name: /get_loan_account/ });
    await row.waitFor({ timeout: 120_000 });
    const sidePanel = await page.getByTestId('module-test-panel').count();
    await row.click();
    await page.waitForURL(`**/tools/${MODULE}/operations/get_loan_account`, { timeout: 60_000 });
    const panel = page.getByTestId('module-test-panel');
    await panel.waitFor({ timeout: 120_000 });
    const [panelBox, benchBox] = [await panel.boundingBox(), await page.getByTestId('tool-workbench').boundingBox()];
    check('a row opens the operation with its run beside its definition', sidePanel === 0 && !!panelBox && !!benchBox && panelBox.x > benchBox.x + 400, { sidePanel, panelBox, benchBox });
    check('there is no Test console tab', (await page.getByRole('tab', { name: 'Test console' }).count()) === 0);

    // Allow: get_loan_account run as the lending inbox case, which is approved for it; the case binds the account.
    await panel.getByRole('button', { name: 'Run', exact: true }).click();
    const allowed = await panel.getByText('Allowed').waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('an approved operation run against the stub is allowed', allowed && (await panel.getByText('HTTP 200').count()) === 1);

    // Non-vacuous pair: transfer_funds is hidden in this module, so the gateway refuses a valid input for it.
    await page.goto(`${consoleUrl}/tools/${MODULE}/operations/transfer_funds`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await panel.waitFor({ timeout: 120_000 });
    await panel.getByLabel('toAccount').fill('CHQ-1182');
    await panel.getByLabel('amount').fill('100');
    await panel.getByRole('button', { name: 'Run', exact: true }).click();
    const denied = await panel.getByText('The operation is hidden in this module.', { exact: true }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('a hidden operation is denied with its reason', denied && (await panel.getByText('HTTP 403').count()) === 1, (await panel.innerText()).slice(-300));

    await page.goto(`${consoleUrl}/tools/${MODULE}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByRole('tab', { name: 'Activity' }).click({ timeout: 120_000 });
    const firstRow = page.locator('[data-testid^="execution-row-"]').first();
    const listed = await firstRow.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    const caller = listed ? (await firstRow.getByTestId('caller-cell').innerText()).split('\n') : [];
    check('executions list a caller and who it acted via', caller.length === 2 && caller[0].length > 0 && caller[1].startsWith('via '), caller);

    await firstRow.getByTestId('caller-cell').click();
    const sheet = page.getByTestId('tool-call-sheet');
    const opened = await sheet.waitFor({ timeout: 30_000 }).then(() => true, () => false);
    check('a row opens the call with its workflow', opened && (await sheet.getByText(caller[0] ?? '-', { exact: true }).count()) > 0, opened ? 'workflow not in the sheet' : 'sheet not open');
    await page.keyboard.press('Escape');

    await page.setViewportSize({ width: 375, height: 800 });
    await page.waitForTimeout(500);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check('no sideways scroll at phone width', overflow <= 0, `${overflow}px wider than the viewport`);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
