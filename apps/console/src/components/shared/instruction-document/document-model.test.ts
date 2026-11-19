// The instruction document's stored format, by failure mode: a save that loses or rewrites a reference id, a chip that
// keeps an item's old name after a rename, and a removed item that still reads as present.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { ReferenceItem } from '@/lib/types/references';

import { type DocumentValue, chipFor, fromEditorDoc, missingReferences, parseText, serializeSegments, toEditorDoc } from './document-model.ts';

const item = (kind: ReferenceItem['kind'], id: string, label: string): ReferenceItem => ({ kind, id, label, hint: null, held: true, adds: null, needsApproval: false, disabled: null });

const doc: DocumentValue = {
  blocks: [
    { kind: 'field', key: 'brief.purpose', label: 'Purpose', locked: true, text: 'Settles card disputes under 500 dollars.' },
    // A reference before a full stop, two lines, an email address, a literal {{ and a variable.
    { kind: 'field', key: 'brief.howToAnswer', label: 'How to answer', locked: true, text: 'Check the case with @tool:dispute.status-lookup.\nWrite to help@harbor.example, greet {{customer.first_name}} and never print {{ or @tool: alone.' },
    { kind: 'list', key: 'brief.never', label: 'Never', items: ['Promise a refund before @skill:verify_identity passes.', 'Read out a full card number.'] },
    {
      kind: 'steps',
      steps: [
        { do: 'Ask which charge looks wrong.' },
        { do: 'Open the dispute and read @knowledge:kb_42.', use: { kind: 'tool', id: 'open_dispute' }, check: { text: 'result.amount <= 500', by: 'rule' }, ifNot: { action: 'goto', step: 1 } },
        { do: 'Tell the customer the outcome.', check: { text: 'The customer has the case number' }, ifNot: { action: 'retry', retries: 2 } },
      ],
    },
  ],
};

test('a document comes back from the editor with every reference id, check and if-not as stored', () => {
  assert.deepEqual(fromEditorDoc(toEditorDoc(doc)), doc);
  // The full stop after a reference is text, not part of the id.
  assert.deepEqual(parseText('Use @tool:dispute.status-lookup.')[1], { t: 'ref', kind: 'tool', id: 'dispute.status-lookup' });
  // Text typed straight after a chip, or a chip put straight after a word, must not change which item it names.
  const typed = serializeSegments([{ t: 'text', text: 'see' }, { t: 'ref', kind: 'tool', id: 'open_dispute' }, { t: 'text', text: 's.now' }]);
  assert.deepEqual(parseText(typed).filter((s) => s.t === 'ref'), [{ t: 'ref', kind: 'tool', id: 'open_dispute' }]);
  // A letter or digit of any script counts as a word, as it does where the text is stored: text typed straight
  // before `@` makes no chip, and a chip put there is written with a space so the service reads it as one too.
  for (const word of ['café', '顧客', '٣']) {
    assert.deepEqual(parseText(`${word}@tool:open_dispute`), [{ t: 'text', text: `${word}@tool:open_dispute` }]);
    assert.equal(serializeSegments([{ t: 'text', text: word }, { t: 'ref', kind: 'tool', id: 'open_dispute' }]), `${word} @tool:open_dispute`);
  }
});

test('a renamed item shows its new name on the chip, with the stored text unchanged', () => {
  const ref = { kind: 'tool', id: 'open_dispute' } as const;
  assert.deepEqual(chipFor(ref, [item('tool', 'open_dispute', 'Open dispute')]), { state: 'ok', label: 'Open dispute' });
  assert.deepEqual(chipFor(ref, [item('tool', 'open_dispute', 'Open a card dispute')]), { state: 'ok', label: 'Open a card dispute' });
});

test('a removed item shows as Missing and is reported, but not while the names are still loading', () => {
  const resolved = [item('tool', 'dispute.status-lookup', 'Dispute status lookup'), item('skill', 'verify_identity', 'Verify identity'), item('knowledge', 'kb_42', 'Card dispute handbook')];
  assert.deepEqual(chipFor({ kind: 'tool', id: 'open_dispute' }, resolved), { state: 'missing', label: 'Missing: open_dispute' });
  assert.deepEqual(missingReferences(doc, resolved), [{ kind: 'tool', id: 'open_dispute' }]);
  // The same id under another kind is a different item.
  assert.equal(chipFor({ kind: 'skill', id: 'kb_42' }, resolved).state, 'missing');
  assert.equal(chipFor({ kind: 'tool', id: 'open_dispute' }, undefined).state, 'loading');
  assert.deepEqual(missingReferences(doc, undefined), []);
});
