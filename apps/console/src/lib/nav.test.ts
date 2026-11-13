import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AREAS, type NavNeed, rowsOfArea, sidebarSections } from './nav.ts';

const everything = () => true;

// The one sidebar must list every page the area tabs offer, each once, or a page becomes unreachable from the sidebar.
test('an admin sees five sections holding every row of every area exactly once', () => {
  const sections = sidebarSections(everything);
  assert.deepEqual(sections.map((s) => s.label), ['Work', 'Agent Builder', 'Workflows', 'Data Gateway', 'Governance']);
  const listed = sections.flatMap((s) => s.items.map((i) => i.url));
  const offered = AREAS.flatMap((a) => rowsOfArea(a, everything).map((i) => i.url));
  assert.deepEqual([...listed].sort(), [...offered].sort());
  assert.equal(new Set(listed).size, listed.length);
});

// A person who only chats has no page in any section, so no empty heading is drawn above nothing.
test('a section with no row the person may open is left out', () => {
  const chatOnly = (needs?: NavNeed) => needs?.area === 'chat';
  assert.deepEqual(sidebarSections(chatOnly), []);
});
