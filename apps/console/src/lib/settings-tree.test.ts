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

// models-service refuses connections and aliases to anyone without settings.manage, so the rail offers the Models pages
// only to a person who holds that cell, and draws no Models heading above nothing.
test('the settings rail offers Models to someone who may manage settings and hides it from everyone else', () => {
  const MODELS = ['section-Models', 'model-connections', 'model-aliases'];
  const manager = (needs?: NavNeed) => !needs || (needs.area === 'settings' && needs.action === 'manage');
  const noSettings = (needs?: NavNeed) => !needs || needs.area === 'chat';
  assert.deepEqual(MODELS.filter((id) => pages(manager).includes(id)), MODELS);
  assert.deepEqual(MODELS.filter((id) => pages(noSettings).includes(id)), []);
});
