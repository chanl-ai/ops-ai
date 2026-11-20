import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { NavNeed } from './nav.ts';
import { LIVE_TREE, offeredGroups } from './settings-tree.ts';

const pages = (allows: (needs?: NavNeed) => boolean) =>
  offeredGroups(LIVE_TREE, allows).flatMap((g) => g.items.flatMap((i) => [i.id, ...(i.children ?? []).map((c) => c.id)]));
const POLICY_PAGES = ['section-Policies', 'policies', 'approvals', 'publish-reviews', 'gates'];

// A chat user holds only chat and their own memory: the policy pages' reads (/policies, the gates) refuse them, so the
// rail offers neither the pages nor the Policies heading above them.
test('the settings rail offers the policy pages to an admin and hides them from a chat user', () => {
  assert.deepEqual(POLICY_PAGES.filter((id) => pages(() => true).includes(id)), POLICY_PAGES);
  const chatOnly = (needs?: NavNeed) => !needs || needs.area === 'chat' || needs.area === 'memory';
  assert.deepEqual(POLICY_PAGES.filter((id) => pages(chatOnly).includes(id)), []);
});
