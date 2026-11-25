// The agent page's Add tools picker as a person drives it, shared by every ui script that grants a tool: open Add tools,
// type a word, click the tool the search names under its app (or open an app and tick its first tool), and close.
// Test ids are the picker's own (apps/console/src/components/agents/agent-tools-picker.tsx).

/** Presses Add tools and waits for the picker's search. */
export async function openToolsPicker(page) {
  await page.getByTestId('agent-tools-picker').first().click({ timeout: 120_000 });
  await page.getByTestId('tools-picker-search').waitFor({ timeout: 60_000 });
}

/** Opens Add tools and types `search`; returns the tool the search names under its app (`toolId`, or the first one). */
export async function findMatchedTool(page, search, toolId) {
  await openToolsPicker(page);
  return searchMatchedTool(page, search, toolId);
}

/** Types `search` in the open picker; returns the tool it names under its app (`toolId`, or the first one). */
export async function searchMatchedTool(page, search, toolId) {
  const box = page.getByTestId('tools-picker-search');
  await box.fill(search);
  // Under the app cards only, and by the whole id: `tools-match-get` must not find `tools-match-get_account`.
  const cards = page.getByTestId('tools-picker-apps');
  const matches = toolId ? cards.getByTestId(`tools-match-${toolId}`) : cards.locator('button[data-testid^="tools-match-"]:not([disabled])');
  return matches.first();
}

/** Clicks a tool found by `findMatchedTool` (it is granted at once) and waits for the dialog to close. */
export async function chooseMatchedTool(page, match) {
  await match.click({ timeout: 60_000 });
  await page.keyboard.press('Escape');
  await page.getByTestId('tools-picker-dialog').waitFor({ state: 'detached', timeout: 30_000 });
}

/** Grants the tool `search` finds, in one go. */
export async function addMatchedTool(page, search, toolId) {
  await chooseMatchedTool(page, await findMatchedTool(page, search, toolId));
}

/** Opens the first app, ticks its first tool not yet held and adds it; returns that tool's label. */
export async function addFirstToolOfFirstApp(page) {
  await openToolsPicker(page);
  // An app's card is the button in the cards list; the app step's own controls share the `tools-app-` prefix
  // (select-all, add, connect, list), so neither lookup is by prefix alone.
  await page.getByTestId('tools-picker-apps').locator('button[data-testid^="tools-app-"]').first().click({ timeout: 60_000 });
  const box = page.getByTestId('tools-app-list').locator('button[role="checkbox"][data-testid^="tools-app-tool-"]:not([disabled])').first();
  await box.waitFor({ timeout: 30_000 });
  const label = (await page.locator(`label[for="${await box.getAttribute('id')}"]`).innerText()).split('\n')[0];
  await box.click();
  await page.getByTestId('tools-app-add').click();
  await page.getByTestId('tools-picker-dialog').waitFor({ state: 'detached', timeout: 30_000 });
  return label;
}

/** Opens the first app row of the Tools section so the tools it holds are listed. */
export async function showHeldTools(page) {
  await page.getByTestId('agent-tools-rows').getByRole('button', { name: /^Show .* tools$/ }).first().click({ timeout: 30_000 });
}
