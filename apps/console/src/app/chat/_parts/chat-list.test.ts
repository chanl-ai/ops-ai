import assert from 'node:assert/strict';
import { test } from 'node:test';

import { chatListParams, chatListPlace } from './chat-list.ts';

// One list of chats: in the column on the chat pages with the single sidebar, in the sidebar with area tabs, never both.
test('with the single sidebar the list sits in the chat pages column only', () => {
  assert.equal(chatListPlace('off', '/chat'), 'column');
  assert.equal(chatListPlace('off', '/chat/th_1'), 'column');
  assert.equal(chatListPlace('off', '/chat/conversations'), 'none');
  assert.equal(chatListPlace('off', '/cases'), 'none');
});

test('with area tabs on the list stays in the sidebar on every page', () => {
  assert.equal(chatListPlace('on', '/chat/th_1'), 'sidebar');
  assert.equal(chatListPlace('on', '/cases'), 'sidebar');
});

// A column drawn before the flag answers would vanish again when it turns out to be on.
test('while the flag loads the list is drawn nowhere', () => {
  assert.equal(chatListPlace('loading', '/chat'), 'none');
});

// The default read must stay the sidebar's (same query key, one request); a search or "Show more" must page on the server.
test('the list reads pinned and recent by default, and pages on the server when searching or showing more', () => {
  assert.deepEqual(chatListParams('', false), { pageSize: 30, recent: 5, filters: { state: ['active', 'pinned'] } });
  assert.deepEqual(chatListParams('  saskatchewan ', false), { pageSize: 30, search: 'saskatchewan', filters: { state: ['active', 'pinned'] } });
  assert.deepEqual(chatListParams('', true), { pageSize: 30, filters: { state: ['active', 'pinned'] } });
});
