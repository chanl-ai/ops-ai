import type { Fragment, FragmentField } from './ui-fragment';

/** Numbers the fields (and the actions) of a fragment that carry a note, starting after `start`. */
export function pinsFor(fragment: Fragment, start = 0) {
  const pins = new Map<FragmentField | 'actions', number>();
  const notes: { label: string; note: string }[] = [];
  for (const f of fragment.fields) {
    if (!f.note) continue;
    notes.push({ label: f.label, note: f.note });
    pins.set(f, start + notes.length);
  }
  if (fragment.actionsNote) {
    notes.push({ label: fragment.actions.join(' or '), note: fragment.actionsNote });
    pins.set('actions', start + notes.length);
  }
  return { pins, notes };
}
