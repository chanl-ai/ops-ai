import type { PromptSection } from '@/lib/types/prompts';

/** Joins generated sections into the instructions text an agent version stores. */
export const composeInstructions = (sections: PromptSection[]) => sections.map((s) => `## ${s.title}\n${s.body.trim()}`).join('\n\n');

/** Splits instructions written as `## Title` sections back into sections; text before the first heading is one untitled section. */
export function splitInstructions(text: string): PromptSection[] {
  const parts = text.split(/^## /m);
  const out: PromptSection[] = [];
  parts.forEach((p, i) => {
    if (!p.trim()) return;
    if (i === 0 && !text.startsWith('## ')) return out.push({ id: 'intro', title: 'Instructions', body: p.trim() });
    const [title, ...rest] = p.split('\n');
    out.push({ id: `s${i}`, title: title.trim(), body: rest.join('\n').trim() });
  });
  return out;
}
