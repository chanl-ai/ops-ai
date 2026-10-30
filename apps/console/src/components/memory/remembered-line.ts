import type { RememberedItem } from '@/lib/types/chat';

const DONE: Record<NonNullable<RememberedItem['decision']>, string> = {
  new: 'Remembered',
  same: 'Already remembered',
  replaces: 'Updated',
  conflicts: 'Not changed, since it differs from what you told me before',
};

/**
 * A reply's memory line in plain words: what it kept, by value. Only the memory's person gets values, so anyone else
 * reading the thread sees how many, and a forgotten memory shows as forgotten with no text.
 */
export function rememberedLine(items: RememberedItem[]): string {
  const said = items.flatMap((r) => {
    if (r.status === 'forgotten') return ['Forgotten'];
    if (!r.value) return [];
    if (r.status === 'suggested') return [`Suggested: ${r.value}`];
    return [`${DONE[r.decision ?? 'new']}: ${r.value}`];
  });
  if (said.length) return said.join(' · ');
  return items.length === 1 ? 'Remembered 1 thing' : `Remembered ${items.length} things`;
}
