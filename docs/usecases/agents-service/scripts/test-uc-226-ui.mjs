// uc-226 a mailbox workflow takes every shape of email, ui layer: docs/usecases/agents-service/every-shape-of-email.md.
// The emails arrive as the Email received trigger hands them on; James reads each run's page: the way it took, a run
// per attachment, and where it ended. Maya opens the read check an email and its attachment disagree on and sees both
// case numbers. Platform sign-in, documents-service and the demo's fake model; no real model is called.
import { FILES_PORT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, as, readRunPage, readStepSheet, saveAndPublish, settled, start } from '../../lib/workflow_ui.mjs';
import { MAIL, MARCUS, PRIYA, READ_ONE, notice, upload } from './uc226_mail.mjs';

const files = `http://127.0.0.1:${FILES_PORT}`;

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker({ OPS_FILES_URL: files });
    const J = await as(JAMES);
    const published = [await saveAndPublish(J, READ_ONE), await saveAndPublish(J, MAIL)];
    if (!published.every((p) => p.live)) throw new Error(`setup: the workflows did not go live: ${published.map((p) => p.saved.status).join(', ')}`);
    const mail = (input) => start(J, MAIL.id, input, { mode: 'live' });

    const text = await upload(J, 'email-body.txt', notice('UC226 BODY ONLY', ...MARCUS, 'NS-2026-GN-01187'), 'email_body');
    const onlyText = await mail({ attachments: [], bodyFile: text });
    const a = await upload(J, 'notice-a.txt', notice('UC226 ATTACHMENT A', ...MARCUS, 'NS-2026-GN-01187'), 'case_attachment');
    const b = await upload(J, 'notice-b.txt', notice('UC226 ATTACHMENT B', ...PRIYA, 'ON-2026-GN-04421'), 'case_attachment');
    const two = await mail({ attachments: [a, b], bodyFile: null });
    const c = await upload(J, 'notice-c.txt', notice('UC226 ATTACHMENT C', ...MARCUS, 'NS-2026-GN-01187'), 'case_attachment');
    const t = await upload(J, 'email-body.txt', notice('UC226 BODY CONFLICT', ...MARCUS, 'NS-2026-GN-01188'), 'email_body');
    const both = await mail({ attachments: [c], bodyFile: t });
    for (const id of [onlyText, two]) await settled(J, id);
    const waiting = await settled(J, both, { orWaiting: true });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const textPage = await readRunPage(page, consoleUrl, onlyText);
      const way = await readStepSheet(page, 'what');
      check('2 an email with no attachment is read from its text: its run took the text-only way and ended at Text read', textPage.outcome === 'text_read' && way.port === 'text_only', { outcome: textPage.outcome, way: way.port });

      const twoPage = await readRunPage(page, consoleUrl, two);
      const kids = await Promise.all(twoPage.children.map((id) => settled(J, id)));
      check(
        '3 an email with two attachments lists a run per attachment on its page, each ending at Read',
        twoPage.outcome === 'dispatched' && twoPage.children.length === 2 && kids.every((k) => k?.outcome === 'read'),
        { outcome: twoPage.outcome, children: twoPage.children, kids: kids.map((k) => k?.outcome) },
      );

      // Maya, a reviewer of the team, opens the read check from Human Tasks and sees both case numbers side by side.
      const maya = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      await maya.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(`${both}:${waiting?.waiting?.node ?? 'check'}:${waiting?.waiting?.iteration ?? 1}`)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByTestId('decision-panel').waitFor({ timeout: 60_000 });
      const shown = (await maya.locator('main').innerText()).replace(/\s+/g, ' ');
      check(
        '4 a text and an attachment that disagree stop at the read check, which shows both case numbers',
        waiting?.status === 'waiting' && waiting?.waiting?.node === 'check' && shown.includes('NS-2026-GN-01187') && shown.includes('NS-2026-GN-01188'),
        { status: waiting?.status, at: waiting?.waiting?.node, shown: shown.slice(0, 400) },
      );
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
