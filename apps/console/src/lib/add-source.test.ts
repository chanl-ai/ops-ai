import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createInput, firstSyncCalls, kindsToConnect, kindUnavailable, strategiesWith } from './add-source.ts';
import type { SourceKindOption } from './types/knowledge.ts';

const defaults = (strategies: string[]) =>
  ({
    parsing: { ocr: 'auto', tables: true, vision: false },
    cleaning: { furniture: true, mainContent: true, siteRepeats: true, duplicates: 'flag' },
    ingest: { preset: 'help_centre', strategies, size: 400, overlap: 40, childSize: 120, questionsPerSection: 3, columns: [], model: 'bank-standard', approval: { status: 'not_needed', approvedSteps: [] } },
    rules: [],
    metadataMapping: [],
    schedule: { kind: 'daily', time: '02:00', tz: 'UTC' },
  }) as unknown as SourceKindOption['defaults'];

const website: SourceKindOption = { type: 'tool', kind: 'web', group: 'apps', title: 'Website', plugin: 'web', source: 'site', site: true, previews: true, inputs: { start: { type: 'string' } }, defaults: defaults(['structure', 'context_headers', 'faq']) };
const files: SourceKindOption = { type: 'file', kind: 'file', group: 'built_in', title: 'Files', defaults: defaults(['structure', 'context_headers']) };

test('switching the AI steps keeps the kind’s other steps and never repeats one', () => {
  assert.deepEqual(strategiesWith(['structure', 'faq', 'context_headers'], { questions: false, drafts: true }), ['structure', 'context_headers', 'faq_pairs']);
  assert.deepEqual(strategiesWith(['structure', 'faq'], { questions: true, drafts: false }), ['structure', 'faq']);
});

test('a website source sends its plugin, source and values; a file source sends its file ids and no plugin', () => {
  const web = createInput({ kind: website, name: ' Claims help ', values: { start: 'https://help.example.com' }, schedule: { kind: 'manual' }, ai: { questions: true, drafts: false }, fileIds: ['f1'] });
  assert.deepEqual(web.config, { plugin: 'web', source: 'site', values: { start: 'https://help.example.com' } });
  assert.equal(web.name, 'Claims help');
  assert.equal(web.fileIds, undefined);
  const file = createInput({ kind: files, name: 'Rate sheets', values: {}, schedule: { kind: 'manual' }, ai: { questions: false, drafts: false }, fileIds: ['f1', 'f2'] });
  assert.deepEqual(file.config, {});
  assert.deepEqual(file.fileIds, ['f1', 'f2']);
  assert.deepEqual(file.ingest?.strategies, ['structure', 'context_headers']);
});

test('the first sync’s calls are a range per step turned on, and none when no step is on', () => {
  assert.equal(firstSyncCalls(141, { questions: false, drafts: false }), null);
  assert.deepEqual(firstSyncCalls(141, { questions: true, drafts: false }), { low: 141, high: 705 });
  assert.deepEqual(firstSyncCalls(10, { questions: true, drafts: true }), { low: 20, high: 100 });
});

const tool = { type: 'tool', kind: 'tool', group: 'apps', needsConnection: true, connected: false, plugin: 'salesforce' } as const;

test('an app that is on but not connected keeps its connect link, though create refuses it', () => {
  const missing = { ...tool, title: 'Salesforce', canCreate: false, cannotCreateCode: 'connection_missing' } as const;
  assert.deepEqual(kindsToConnect([missing]), [missing]);
});

test('a connection that signs in each person gets no connect link', () => {
  assert.deepEqual(kindsToConnect([{ ...tool, title: 'Gmail', canCreate: false, cannotCreateCode: 'sign_in_not_team' }]), []);
});

test('a kind is unavailable when it needs a connection it lacks or create would refuse it', () => {
  assert.equal(kindUnavailable({ needsConnection: true, connected: false }), true);
  assert.equal(kindUnavailable({ needsConnection: false, canCreate: false }), true);
  assert.equal(kindUnavailable({ needsConnection: true, connected: true, canCreate: true }), false);
});
