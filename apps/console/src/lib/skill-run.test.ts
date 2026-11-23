// How the chat list reads a reply's skill record: an ending is drawn once, under the reply the server marks, and an
// older reply without the marks draws nothing.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { ChatMessage, SkillRun } from './types/chat.ts';
import { endedInReply, endingText, holdsText, newestRun } from './skill-run.ts';

const reply = (id: string, skillRun: SkillRun | null): ChatMessage => ({ id, role: 'assistant', content: 'ok', at: '2026-11-19T10:00:00Z', skillRun });
const denied = { skillId: 'card_dispute', version: 1, name: 'Card dispute', ended: 'failed', atStep: 2, why: 'denied' as const };

test('a rejected action is told once, under the reply it ended in, and in words that name the skill and step', () => {
  const first = reply('m1', { running: null, history: [{ ...denied, inReply: true }], holds: [{ skillId: 'card_dispute', name: 'Card dispute', step: '2', denied: true, tools: ['open_dispute'] }] });
  // The next reply repeats the record, unmarked.
  const later = reply('m2', { running: null, history: [{ ...denied, inReply: false }] });
  assert.deepEqual(endedInReply(first).map(endingText), ['Card dispute stopped at step 2: a reviewer rejected the action']);
  assert.deepEqual(endedInReply(later), []);
  assert.equal(holdsText(newestRun([first], undefined)), 'Some actions are on hold until Card dispute starts again');
  assert.equal(holdsText(newestRun([first, later])), null);
});

test('an older saved reply has no ending line, and an author exit carries what its author says it means', () => {
  assert.deepEqual(endedInReply(reply('m0', { running: null, history: [{ skillId: 'a', version: 1, name: 'Card dispute', ended: 'failed', atStep: 2 }] })), []);
  assert.equal(endingText({ skillId: 'a', version: 1, name: 'Card dispute', ended: 'blocked', atStep: 4, inReply: true, meaning: 'The customer could not be verified' }), 'Card dispute ended as blocked at step 4: The customer could not be verified');
  assert.equal(endingText({ skillId: 'a', version: 1, name: 'Card dispute', ended: 'failed', atStep: 3, why: 'check', inReply: true }), 'Card dispute stopped at step 3: its check did not pass');
  // The reply still being written has no record yet, so the line stays on the last finished one.
  assert.equal(newestRun([reply('m1', { running: null, history: [] }), reply('m2', null)], 'm2')?.history.length, 0);
});
