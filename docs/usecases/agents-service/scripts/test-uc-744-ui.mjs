// uc-744 Update an opportunity from the same skill, ui layer: docs/usecases/agents-service/update-an-opportunity-from-the-same-skill.md.
// In one chat Priya picks "Prepare a client meeting" and then "Update an opportunity" from the same Salesforce skill; the
// reply shows the second part picked by her and the first carried from the reply before. At 1440 and 390; with
// OPS_USECASE_MEDIA=1 the shots and a GIF of the walk land in docs/usecases/agents-service/media.
import { check, chromium, finish, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';

import { openChat, pickPartAndSend, recordClip, seedChat, usedSkills } from '../../lib/skills_chat_ui.mjs';

await withUiStack(
  async (consoleUrl) => {
    const { newThread } = await seedChat();
    const browser = await chromium.launch();
    try {
      for (const width of [1440, 390]) {
        const thread = await newThread();
        const errors = [];
        const page = await openChat(browser, consoleUrl, thread, width, errors);
        const name = `1 at ${width} the second part is picked and the first is carried, both on the reply's Used skill lines`;
        try {
          const box = page.getByRole('textbox', { name: 'Message' });
          await box.click();
          await box.pressSequentially('/');
          await page.getByTestId('skill-menu').waitFor({ timeout: 30_000 });
          await shootBothWidths(page, 'agents-service', `uc-744-menu`, async () => page.waitForTimeout(400));
          await page.setViewportSize({ width, height: width > 600 ? 1000 : 844 });
          await box.fill('');
          await pickPartAndSend(page, 'Prepare a client meeting', 'Okafor Family Trust', 'Prepare my meeting');
          await pickPartAndSend(page, 'Update an opportunity', 'Okafor Family Trust', 'They agreed to $75,000, move it forward a stage');
          const line = usedSkills(page);
          await line.waitFor({ timeout: 60_000 });
          const said = (await line.innerText()).replace(/\s+/g, ' ');
          await shootBothWidths(page, 'agents-service', `uc-744-used-skill`, async () => page.waitForTimeout(400));
          check(name, /update opportunity.*picked by you/.test(said) && /prepare meeting.*carried from the reply before/.test(said), said);
        } catch (e) {
          check(name, false, `${String(e).slice(0, 300)} at ${page.url()}`);
        }
        check(`2 at ${width} no page errors`, errors.length === 0, errors.slice(0, 3));
        await page.context().close();
      }
      // The clip: one full walk at 1440.
      await recordClip(browser, consoleUrl, await newThread(), 'uc-744-slash-menu', async (page) => {
        await pickPartAndSend(page, 'Prepare a client meeting', 'Okafor Family Trust', 'Prepare my meeting');
        await pickPartAndSend(page, 'Update an opportunity', 'Okafor Family Trust', 'They agreed to $75,000');
        await usedSkills(page).waitFor({ timeout: 60_000 });
      });
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
