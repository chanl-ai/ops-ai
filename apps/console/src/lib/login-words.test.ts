import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { test } from 'node:test';

import { connectWaitActions, signInFor, signInChoiceWords, signInTitle, teamLoginLines } from './login-words.ts';

// How a chat user meets an app's login, by failure mode: a team-login action that does not say who acted, a sign-in
// card in other words than the app setting, a Human Task that offers the person both their own login and the team's,
// and a screen that still says "team account" where every other one says "login".

test('a team-login action says once per app which login acted and that the person asked', () => {
  const team = { whose: 'team' as const, login: 'ops@harborpine.example', app: 'Salesforce' };
  const calls = [
    { server: 'Salesforce', signedIn: team },
    { server: 'Salesforce', signedIn: team },
    { server: 'Zendesk', signedIn: { whose: 'person' as const, login: 'james@harborpine.example', app: 'Zendesk' } },
    { server: 'kernel' },
  ];
  assert.deepEqual(teamLoginLines(calls), ['Runs in Salesforce as ops@harborpine.example (team login). You are recorded as the person who asked.']);
});

test('the app setting has two answers in the words the chat and the guide use', () => {
  assert.equal(signInChoiceWords('team'), 'Everyone uses the team’s login');
  assert.equal(signInChoiceWords('person'), 'Each person signs in');
  assert.equal(signInTitle('Salesforce'), 'Sign in to Salesforce to continue');
});

test('Each person signs in saves each person only, never the team login as a backup', () => {
  assert.equal(signInFor('each'), 'person');
  assert.equal(signInFor('shared'), 'team');
});

test('a Human Task never offers the person it waits for a choice between their login and the team’s', () => {
  assert.deepEqual(connectWaitActions({ mine: true, teamLogin: true, mayRunAsTeam: true }), ['sign_in']);
  assert.deepEqual(connectWaitActions({ mine: false, teamLogin: true, mayRunAsTeam: true }), ['run_as_team']);
  assert.deepEqual(connectWaitActions({ mine: false, teamLogin: true, mayRunAsTeam: false }), []);
});

/** Every line of the console's source a person can read: comments and test files left out. */
function shownLines(dir: string): { file: string; line: string }[] {
  const out: { file: string; line: string }[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== 'mock' && name !== 'node_modules') out.push(...shownLines(path));
      continue;
    }
    if (!/\.tsx?$/.test(name) || /\.test\.tsx?$/.test(name)) continue;
    for (const line of readFileSync(path, 'utf8').split('\n')) {
      const code = line.trim();
      if (code.startsWith('//') || code.startsWith('*') || code.startsWith('/*') || code.startsWith('{/*')) continue;
      out.push({ file: path, line: code.replace(/\/\/.*$/, '') });
    }
  }
  return out;
}

test('no screen says "team account" for an app’s sign-in: it is the team’s login', () => {
  const src = new URL('..', import.meta.url).pathname;
  const hits = shownLines(src).filter((l) => /team(’s|'s)? account/i.test(l.line));
  assert.deepEqual(hits.map((h) => `${relative(src, h.file)}: ${h.line.slice(0, 120)}`), []);
});
