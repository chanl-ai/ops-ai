// uc-767 a person who only chats sees My apps in the sidebar and can chat, ui layer:
// docs/usecases/console/chat-only-person-my-apps.md. Demo stack signed in through platform-service as Lena (chat user
// in Operations, no builder cells): the sidebar offers Chat and My apps and nothing she cannot open; the scripted
// model answers her chat.
import { check, chromium, consoleSignIn, finish, replyDone, shootBothWidths, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD } from '@ops-ai/usecase-runner/steps';

const LENA = 'l.brandt@harborpine.example';
const MESSAGES = /\/chat\/threads\/[^/]+\/messages$/;
const armed = (p) => (p.catch(() => undefined), p);

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, LENA, PASSWORD, errors);
      page.setDefaultTimeout(30_000);
      const rows = async () => (await page.locator('[data-sidebar=header] a, [data-sidebar=content] a').allInnerTexts()).map((t) => t.split('\n')[0].trim()).filter(Boolean);
      const settled = async () => {
        await page.locator('[data-sidebar=content] a').first().waitFor({ timeout: 45_000 });
        await page.locator('[data-sidebar=content] [data-slot=skeleton]').first().waitFor({ state: 'detached', timeout: 30_000 }).catch(() => undefined);
      };

      await step('1 the sidebar offers Chat and My apps and nothing a builder holds', async () => {
        await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await settled();
        const seen = await rows();
        const none = ['Agents', 'Workflows', 'Cases', 'Activity', 'Settings'];
        await shootBothWidths(page, 'console', 'uc-767-sidebar', async () => page.waitForTimeout(300));
        await page.setViewportSize({ width: 1440, height: 1000 });
        check('1 the sidebar offers Chat and My apps and nothing a builder holds', seen.includes('Chat') && seen.includes('My apps') && none.every((n) => !seen.includes(n)), seen);
      });

      await step('2 My apps opens her own sign-ins page', async () => {
        await page.locator('[data-sidebar=content] a', { hasText: /^My apps$/ }).first().click();
        await page.waitForURL((u) => u.pathname === '/settings/account/connectors', { timeout: 30_000 });
        const title = (await page.getByTestId('page-title').first().innerText()).trim();
        check('2 My apps opens her own sign-ins page', title === 'My apps', { url: page.url(), title });
      });

      await step('3 she asks in Chat and the agent answers', async () => {
        await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const suggestion = 'What is the daily wire limit for a personal account?';
        const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && MESSAGES.test(r.url()), { timeout: 120_000 }));
        await page.getByRole('textbox').last().fill(suggestion);
        await page.getByRole('button', { name: 'Send', exact: true }).click();
        const res = await sent;
        await replyDone(res, 60_000);
        const answered = await page.getByRole('button', { name: 'Regenerate' }).waitFor({ timeout: 60_000 }).then(() => true, () => false);
        check('3 she asks in Chat and the agent answers', !!res && res.status() < 300 && answered && /\/chat\/th_/.test(page.url()), { suggestion, status: res?.status(), url: page.url() });
      });

      await step('4 a page that is not hers is refused and the sidebar still holds nothing more', async () => {
        await page.goto(`${consoleUrl}/build/agents`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await settled();
        const seen = await rows();
        check('4 a page that is not hers is refused and the sidebar still holds nothing more', !seen.includes('Agents') && seen.includes('My apps'), { url: page.url(), seen });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
