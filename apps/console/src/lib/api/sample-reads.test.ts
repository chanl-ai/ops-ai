import assert from 'node:assert/strict';
import { test } from 'node:test';

import { recordMockReads, SAMPLE_READ_MARK, sampleReadsOn } from './sample-reads.ts';

test('a mock read beside real services writes the line the use-case harness fails on; a real read does not', async () => {
  const g = globalThis as Record<string, unknown>;
  g.window = { location: { pathname: '/build/channels/mcp' } };
  const lines: string[] = [];
  const warn = console.warn;
  console.warn = (line: string) => lines.push(line);
  try {
    const mock = { links: { list: async () => ['sample'], get: async () => 'sample', url: () => 'snippet' } };
    // index.ts overrides one call with a real service and keeps the rest of the area on the mock.
    const api = recordMockReads({ links: { ...mock.links, get: async () => 'real' } }, mock);
    await api.links.get();
    api.links.url();
    await api.links.list();
    assert.deepEqual(lines, [`${SAMPLE_READ_MARK} links.list on /build/channels/mcp`]);
    assert.deepEqual(sampleReadsOn('/build/channels/mcp'), ['links.list']);
  } finally {
    console.warn = warn;
    delete g.window;
  }
});
