// What the skills-in-chat ui scripts (uc-743, uc-744) share: a published Salesforce skill with two parts and a published
// agent of team_ops made through the agents API as the team's admin, and the / menu walk in the chat composer.
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { AGENTS_PORT, check, consoleSignIn, videoToGif } from '@ops-ai/usecase-runner/harness';

export const PRIYA = 'p.shah@harborpine.example';
export const PASSWORD = 'northfield-demo';
const agents = `http://127.0.0.1:${AGENTS_PORT}`;

const PREPARE = {
  slug: 'prepare-meeting',
  name: 'Prepare a client meeting',
  useWhen: 'Use to brief the adviser before a client meeting.',
  instructions: "Read the client's account, open cases and opportunities, then write a one-page brief.",
  inputs: [{ name: 'client', description: "The client's name", required: true }],
};
const UPDATE = {
  slug: 'update-opportunity',
  name: 'Update an opportunity',
  useWhen: 'Use to change an opportunity after a client call.',
  instructions: 'Read the change back to the adviser and ask them to confirm before saving.',
  inputs: [
    { name: 'client', description: "The client's name", required: true },
    { name: 'note', description: 'What was agreed', required: false },
  ],
};

export async function adminCalls() {
  const signed = await (await fetch(`http://127.0.0.1:${process.env.OPS_USECASE_PLATFORM_PORT ?? 8810}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: PRIYA, password: PASSWORD }) })).json();
  const headers = { Authorization: `Bearer ${signed.data.token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
  return async (method, path, body) => {
    const r = await fetch(`${agents}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const json = await r.json().catch(() => null);
    if (!r.ok) throw new Error(`setup: ${method} ${path} answered ${r.status}: ${JSON.stringify(json).slice(0, 300)}`);
    return json.data;
  };
}

/** A published Salesforce skill with two parts and a published agent; `newThread()` opens an empty thread with it. */
export async function seedChat() {
  const call = await adminCalls();
  const made = await call('POST', '/v1/skills', { ownerTeam: 'team_ops', name: 'Salesforce', useWhen: "Use for anything about a client's Salesforce record.", instructions: 'Work only from Salesforce. Say what you read.', parts: [PREPARE, UPDATE] });
  await call('POST', `/v1/skills/${made.id}/publish-requests`, { note: 'use case' });
  const agent = await call('POST', '/v1/agents', { name: 'Desk', role: 'Answers the team' });
  const draft = await call('PATCH', `/v1/agents/${agent.id}`, { toolIds: [] });
  await call('POST', `/v1/agents/${agent.id}/publish-requests`, { version: draft.version });
  return { skill: made.id, newThread: async () => (await call('POST', '/chat/threads', { agentId: agent.id, kbIds: [] })).id };
}

export async function openChat(browser, consoleUrl, thread, width, errors) {
  const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
  await page.setViewportSize({ width, height: width > 600 ? 1000 : 844 });
  await page.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });
  return page;
}

/** Types /, picks `part` from the menu, fills the client, adds it to the message and sends; resolves when the reply ends. */
export async function pickPartAndSend(page, partName, client, words) {
  const box = page.getByRole('textbox', { name: 'Message' });
  await box.click();
  await box.pressSequentially('/');
  const menu = page.getByTestId('skill-menu');
  await menu.waitFor({ timeout: 30_000 });
  await menu.getByRole('option', { name: new RegExp(partName) }).click();
  const form = page.getByTestId('skill-inputs');
  await form.waitFor({ timeout: 15_000 });
  await form.getByLabel(/^Client/).fill(client);
  await form.getByRole('button', { name: 'Add to message' }).click();
  const chip = page.getByTestId('skill-chip');
  await chip.waitFor({ timeout: 15_000 });
  await page.getByRole('textbox', { name: 'Message' }).fill(words);
  const sent = page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 });
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  const res = await sent;
  await page.getByRole('button', { name: 'Stop', exact: true }).waitFor({ state: 'hidden', timeout: 120_000 }).catch(() => undefined);
  return res;
}

/** One walk at 1440 recorded to a GIF: `walk(page)` is what the clip shows, after sign-in and the page are open. */
export async function recordClip(browser, consoleUrl, thread, name, walk) {
  const videos = mkdtempSync(join(tmpdir(), `${name}-video-`));
  const recording = Date.now();
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: videos, size: { width: 1440, height: 900 } } });
  const page = await context.newPage();
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(PRIYA);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  await page.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });
  const started = Date.now();
  await walk(page);
  await page.waitForTimeout(800);
  const clipMs = Date.now() - started;
  await context.close();
  videoToGif(videos, 'agents-service', name, started - recording, clipMs);
}

/** The Used skill lines of the latest reply. */
export const usedSkills = (page) => page.getByTestId('used-skills').last();
export { check };
