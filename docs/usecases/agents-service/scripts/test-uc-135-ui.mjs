// uc-135 people see, correct, forget and export what an agent remembers, ui layer:
// docs/usecases/agents-service/people-manage-agent-memory.md. The scripted model saves what the person says about
// themselves; James chats with the Branch Concierge in team_ops under platform sign-in.
import { readFileSync } from 'node:fs';

import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor('j.richardson@northfieldbank.com')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const created = await (await fetch(`${agentsUrl}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: 'ag_branch', kbIds: [] }) })).json();
    if (!created.data) throw new Error(`thread: ${JSON.stringify(created).slice(0, 300)}`);
    // Whatever earlier runs left with this agent goes first, so the list below is this run's alone.
    await fetch(`${agentsUrl}/v1/me/memories?agentId=ag_branch`, { method: 'DELETE', headers: J });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
      const page = await context.newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/chat/${created.data.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });

      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      await box.fill('Hi. My timezone is Eastern.');
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      const notice = page.getByTestId('saved-to-memory').first();
      await notice.waitFor({ timeout: 120_000 });
      check('1 the reply says what it saved', /Saved to memory: timezone: Eastern/.test(await notice.innerText()), await notice.innerText());

      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByTestId('saved-to-memory').first().waitFor({ timeout: 120_000 });
      await page.getByTestId('open-memory').first().click();
      const sheet = page.getByTestId('memory-sheet');
      const row = sheet.locator('[data-testid="memory-row"][data-key="timezone"]');
      await row.waitFor({ timeout: 60_000 });
      check('2 What I remember lists it, after a reload too', (await row.getByTestId('memory-value').innerText()) === 'Eastern');

      await row.getByTestId('memory-edit').click();
      await row.getByTestId('memory-value-input').fill('Pacific');
      await row.getByTestId('memory-save').click();
      await sheet.getByText('Corrected by you').waitFor({ timeout: 60_000 });
      const kept = (await (await fetch(`${agentsUrl}/v1/me/memories?agentId=ag_branch`, { headers: J })).json()).data;
      check('3 a correction replaces the value', kept.length === 1 && kept[0].value === 'Pacific' && kept[0].source === 'person', kept);

      const download = page.waitForEvent('download', { timeout: 60_000 });
      await sheet.getByTestId('memory-export').click();
      const file = JSON.parse(readFileSync(await (await download).path(), 'utf8'));
      check('4 export downloads the memories and their history', file.memories.some((m) => m.value === 'Pacific') && file.audit.some((a) => a.action === 'correct'), { memories: file.memories.length, audit: file.audit.map((a) => a.action) });

      await sheet.locator('[data-testid="memory-row"][data-key="timezone"]').getByTestId('memory-forget').click();
      await page.getByTestId('delete-memory-confirm-btn').click();
      await sheet.getByTestId('memory-empty').waitFor({ timeout: 60_000 });
      const left = (await (await fetch(`${agentsUrl}/v1/me/memories?agentId=ag_branch`, { headers: J })).json()).data;
      check('5 forget removes it at once', left.length === 0, left);
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
