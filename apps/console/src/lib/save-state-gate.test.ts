import assert from 'node:assert/strict';
import { test } from 'node:test';

import { newGate, settle, shortcutMatches } from './save-state-gate.ts';

test('a save under the show delay never shows Saving, and one that shows stays long enough to read', () => {
  const g = newGate('unsaved');
  // Saves in 120 ms: the line goes unsaved to saved with no Saving between.
  assert.equal(settle(g, 'saving', 0).shown, 'unsaved');
  assert.equal(settle(g, 'saved', 120).shown, 'saved');
  // A slow save shows Saving after the delay, then holds it for the minimum even if the save ends at once.
  const slow = newGate('unsaved');
  assert.equal(settle(slow, 'saving', 0).shown, 'unsaved');
  assert.equal(settle(slow, 'saving', 400).shown, 'saving');
  const done = settle(slow, 'saved', 450);
  assert.equal(done.shown, 'saving');
  assert.equal(done.wakeAt, 400 + 600);
  assert.equal(settle(slow, 'saved', 1000).shown, 'saved');
  // A failure is never held back.
  const f = newGate('saving');
  assert.equal(settle(f, 'failed', 10).shown, 'failed');
});

test('Cmd+S and Ctrl+S match the save shortcut, a bare s or Cmd+Shift+S does not', () => {
  const ev = (o: object) => ({ key: 's', metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, ...o });
  assert.equal(shortcutMatches('mod+s', ev({ metaKey: true })), true);
  assert.equal(shortcutMatches('mod+s', ev({ ctrlKey: true })), true);
  assert.equal(shortcutMatches('mod+s', ev({})), false);
  assert.equal(shortcutMatches('mod+s', ev({ metaKey: true, shiftKey: true })), false);
});
