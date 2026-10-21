// The embed snippet and the loader it names, by failure mode: a team API key (`ok_<id>.<secret>`) or any other
// long-lived credential pasted into a page, where every visitor can read it. The snippet carries only the deployment
// id; the loader receives the session the page's server minted and hands it only to the chat frame's own origin.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { KEY_VARIABLE, SESSION_PATH, snippetFor } from './widget-snippet.ts';

const LOADER = new URL('../../../../services/agents-service/src/ops_agents/static/ops-chat-loader.js', import.meta.url);
const KEYISH = [/ok_[A-Za-z0-9]+\.[A-Za-z0-9]/, /api[-_ ]?key/i, /x-api-key/i, /secret/i, /localStorage/, /document\.cookie/];

test('the snippet is the mint-key flow: the server mints a session, the page loads /embed/v1.js and starts it', () => {
  const { server, page } = snippetFor('https://ops.bank.example/embed/v1.js', 'wd_abc123', 'harborpine');
  assert.match(server, /^curl -X POST https:\/\/ops\.bank\.example\/v1\/widget-deployments\/wd_abc123\/sessions/);
  assert.match(server, new RegExp(`Bearer \\$${KEY_VARIABLE}`));
  assert.match(page, /<script src="https:\/\/ops\.bank\.example\/embed\/v1\.js" async><\/script>/);
  assert.match(page, /OpsChat\.init\(\{\n\s+deployment: "wd_abc123",\n\s+tenant: "harborpine",/);
  assert.ok(page.includes(SESSION_PATH));
  assert.doesNotMatch(page, /widget\/v1\.js|getSsoToken|data-token/);
  for (const k of KEYISH) assert.doesNotMatch(page, k);
  assert.doesNotMatch(server, /wk\.|ok_/);
});

test('a value cannot close the script tag it is written into', () => {
  const { page } = snippetFor('https://ops.bank.example/embed/v1.js', 'wd_</script><b>', 'x');
  assert.equal(page.split('</script>').length - 1, 2);
});

test('the loader holds no key and keeps no session', () => {
  // Code only: the loader's comments may say what it does not hold.
  const js = readFileSync(LOADER, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  for (const k of KEYISH) assert.doesNotMatch(js, k, `ops-chat-loader.js matches ${k}`);
  // The session goes to the chat frame by postMessage to its exact origin, never '*'.
  assert.match(js, /postMessage\(msg, host\)/);
  assert.doesNotMatch(js, /postMessage\([^)]*'\*'\)/);
});
