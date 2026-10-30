// uc-094 another team's file is missing, ui layer: docs/usecases/files-service/file-team-boundary.md. Priya, in
// Operations, uploads a file and opens its page in Files. Sam, signed in to Security, opens the same address: the page
// says not found and names neither the file nor Operations, and Security's Files list does not hold it. Platform sign-in.
import { FILES_PORT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { PASSWORD, PRIYA, as } from '../../lib/workflow_ui.mjs';

const SAM = 's.adeyemi@harborpine.example';
const files = `http://127.0.0.1:${FILES_PORT}`;
const NAME = `ops-only-${Math.random().toString(36).slice(2, 6)}.txt`;

async function upload(headers, name, text) {
  const bytes = Buffer.from(text, 'utf8');
  const ticket = (await (await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers, body: JSON.stringify({ name, size: bytes.length, mime: 'text/plain', purpose: 'case_attachment' }) })).json()).data;
  await fetch(`${files}/v1/files/uploads/${ticket.fileId}/content`, { method: 'PUT', headers: { ...headers, 'Content-Type': 'text/plain' }, body: bytes });
  return (await (await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers })).json()).data.file.id;
}

/** A page's main text once it has drawn the record or its not-found state. */
async function shown(page, url, marker) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.waitForFunction((m) => {
    const t = document.querySelector('main')?.innerText ?? '';
    return t.includes(m) || /Not found|couldn.t find/i.test(t);
  }, marker, { timeout: 60_000 }).catch(() => undefined);
  return (await page.locator('main').innerText().catch(() => '')).replace(/\s+/g, ' ');
}

await withUiStack(
  async (consoleUrl) => {
    const P = await as(PRIYA);
    const fileId = await upload(P, NAME, `kept in Operations ${NAME}`);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const priya = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
      const hers = await shown(priya, `${consoleUrl}/files/${fileId}`, NAME);
      check('8 Priya opens her file in Operations and sees it', hers.includes(NAME) && !/Not found/i.test(hers), hers.slice(0, 200));

      const sam = await consoleSignIn(browser, consoleUrl, SAM, PASSWORD, errors);
      const his = await shown(sam, `${consoleUrl}/files/${fileId}`, NAME);
      const body = his.replace(/^.*?(Not found|We couldn.t find)/i, '$1');
      check("3 Sam, in Security, opens the file's address and is told it is not found", /Not found|couldn.t find/i.test(his) && !his.includes(NAME), his.slice(0, 300));
      check('3 the not-found page names neither the file nor Operations', !/Operations|team_ops/.test(body) && !body.includes(NAME), body.slice(0, 300));

      await sam.goto(`${consoleUrl}/files`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await sam.getByRole('row').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      await sam.waitForTimeout(1000);
      const listed = (await sam.locator('main').innerText().catch(() => '')).includes(NAME);
      check("5 Security's Files list does not hold it", !listed, { listed });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
