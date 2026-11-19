import assert from 'node:assert/strict';
import { test } from 'node:test';

import { AREAS, type NavNeed, rowsOfArea, sidebarSections } from './nav.ts';

const everything = () => true;

// The one sidebar must list every page the area tabs offer, each once, or a page becomes unreachable from the sidebar.
test('an admin sees four sections holding every row of every area exactly once', () => {
  const sections = sidebarSections(everything);
  assert.deepEqual(sections.map((s) => s.label), ['Work', 'Agent Builder', 'Data Gateway', 'Governance']);
  // Owner, 12 November: Workflows sits under Agents, then Channels.
  assert.deepEqual(sections[1].items.slice(0, 3).map((i) => i.title), ['Agents', 'Workflows', 'Channels']);
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

// One short link per page: a child page is a tab on its parent, so no sidebar row carries sub-rows.
test('no sidebar row carries child pages, and a title repeating its section is shortened', () => {
  const items = sidebarSections(everything).flatMap((s) => s.items);
  assert.deepEqual(items.filter((i) => i.children?.length).map((i) => i.title), []);
  assert.ok(items.some((i) => i.title === 'Knowledge') && !items.some((i) => i.title === 'Knowledge bases'));
});
