// uc-743 Prepare a client meeting from the slash menu, ui layer: docs/usecases/agents-service/prepare-a-meeting-from-the-slash-menu.md.
// Priya types / in a chat with a published agent, picks the Salesforce skill's "Prepare a client meeting" part, fills the
// client, sends, and the reply shows "Used skill Salesforce · prepare meeting ... picked by you". At 1440 and 390; with
// OPS_USECASE_MEDIA=1 the shots and a GIF of the walk land in docs/usecases/agents-service/media.
import { check, chromium, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';

import { openChat, pickPart, pickPartAndSend, sendWords, recordClip, seedChat, usedSkills } from '../../lib/skills_chat_ui.mjs';

await withUiStack(
  async (consoleUrl) => {
    const { newThread } = await seedChat();
    const browser = await chromium.launch();
    try {
      for (const width of [1440, 390]) {
        const thread = await newThread();
        const errors = [];
        const page = await openChat(browser, consoleUrl, thread, width, errors);
        const name = `1 at ${width} / opens the menu, the part's client is filled, and the reply shows the skill chip and the Used skill line`;
        try {
          const box = page.getByRole('textbox', { name: 'Message' });
          await box.click();
          await box.pressSequentially('/');
          await page.getByTestId('skill-menu').waitFor({ timeout: 30_000 });
          await shootBothWidths(page, 'agents-service', `uc-743-menu`, async () => page.waitForTimeout(400));
          await page.setViewportSize({ width, height: width > 600 ? 1000 : 844 });
          await box.fill('');
          await pickPart(page, 'Prepare a client meeting');
          check(`1a at ${width} picking adds a chip and opens no form`, (await page.getByTestId('skill-inputs').count()) === 0);
          await box.fill('Prepare my meeting');
          await page.getByRole('button', { name: 'Send', exact: true }).first().click();
          const dialog = page.getByTestId('skill-inputs');
          await dialog.waitFor({ timeout: 15_000 });
          const labels = await dialog.locator('label').allInnerTexts();
          check(`1b at ${width} the dialog asks only for the missing client, and fits the screen`, labels.length === 1 && /^Client/.test(labels[0]) && (await dialog.boundingBox()).y >= 0, labels);
          await shootBothWidths(page, 'agents-service', `uc-743-dialog`, async () => page.waitForTimeout(400));
          await page.setViewportSize({ width, height: width > 600 ? 1000 : 844 });
          await dialog.getByLabel(/^Client/).fill('Okafor Family Trust');
          await dialog.getByRole('button', { name: 'Send', exact: true }).click();
          await page.getByRole('button', { name: 'Stop', exact: true }).waitFor({ state: 'hidden', timeout: 120_000 }).catch(() => undefined);
          const line = usedSkills(page);
          await line.waitFor({ timeout: 60_000 });
          const said = (await line.innerText()).replace(/\s+/g, ' ');
          await shootBothWidths(page, 'agents-service', `uc-743-used-skill`, async () => page.waitForTimeout(400));
          check(name, /Used skill Salesforce · prepare meeting/.test(said) && /picked by you/.test(said) && /Okafor Family Trust/.test(said), said);
        } catch (e) {
          check(name, false, `${String(e).slice(0, 300)} at ${page.url()}`);
        }
        // A skill with nothing required sends at once, with no dialog.
        try {
          await pickPart(page, 'Weekly summary');
          const res = await sendWords(page, 'Summarise this week');
          check(`3 at ${width} a skill with no required input sends at once`, res.ok() && (await page.getByTestId('skill-inputs').count()) === 0);
        } catch (e) {
          check(`3 at ${width} a skill with no required input sends at once`, false, String(e).slice(0, 300));
        }
        check(`2 at ${width} no page errors`, errors.length === 0, errors.slice(0, 3));
        await page.context().close();
      }
      // The clip: one full walk at 1440.
      await recordClip(browser, consoleUrl, await newThread(), 'uc-743-slash-menu', async (page) => {
        await pickPartAndSend(page, 'Prepare a client meeting', 'Okafor Family Trust', 'Prepare my meeting');
        await usedSkills(page).waitFor({ timeout: 60_000 });
      });
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
