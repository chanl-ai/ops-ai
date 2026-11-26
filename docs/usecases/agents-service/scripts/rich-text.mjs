// Helpers for the shared rich text editor on the skill page: its text box, one line of the stored text, and the
// Markdown view, which sets a whole text in one step.

/** The editor's text box (the contenteditable element); a read-only copy of the text beside it is not it. */
export const textBox = (page) => page.locator('[data-testid="rich-text"][contenteditable="true"]');

/** The block that holds a line of the text. A paragraph keeps its lines, so a block may hold several. */
export const lineOf = (page, text) => textBox(page).locator('p, li, h1, h2, h3', { hasText: text }).first();

/** Puts the caret at the end of the line that holds `text`, as a click and the End key did in a one-line-per-row editor. */
export async function caretAtLineEnd(page, text) {
  await lineOf(page, text).waitFor();
  await textBox(page).focus();
  await page.evaluate((needle) => {
    const box = document.querySelector('[data-testid="rich-text"][contenteditable="true"]');
    const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const at = n.textContent.indexOf(needle);
      if (at < 0) continue;
      const next = n.textContent.indexOf('\n', at);
      const end = next < 0 ? n.textContent.length : next;
      const range = document.createRange();
      range.setStart(n, end);
      range.collapse(true);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      return;
    }
  }, text);
}

/** Switches the editor to the Markdown or the Formatted view, from the bar or, at phone width, from its menu. */
export async function showView(page, view) {
  const bar = page.getByTestId(`rte-view-${view}`);
  if (await bar.isVisible()) return bar.click();
  await page.getByTestId('rte-menu').click();
  await page.getByTestId(`rte-menu-view-${view}`).click();
  // The menu closes with an animation; opening it again before it is gone would press its button as a close.
  await page.locator('[role="menu"]').waitFor({ state: 'detached', timeout: 10_000 });
}

/** Replaces the whole text through the Markdown view and returns to the formatted one. */
export async function setText(page, text) {
  await showView(page, 'markdown');
  await page.getByTestId('rte-markdown').fill(text);
  await showView(page, 'formatted');
}
