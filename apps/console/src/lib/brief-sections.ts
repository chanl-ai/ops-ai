import type { AgentBrief, BriefSection, InstructionSection } from '@/lib/types/domain';

/** The id of the one list entry a builder's own sections share. */
export const CUSTOM_ID = 'custom';
export const CUSTOM_NAME_MAX = 40;
/** Headings the brief writes itself or keeps for old versions, beside every label in the workspace's list. */
const EXTRA_RESERVED = ['Job', 'Who you are', 'Success checks'];

const folded = (name: string) => name.split(/\s+/).filter(Boolean).join(' ').toLowerCase();

/** The list in the order the prompt writes it. */
export const inOrder = (list: readonly InstructionSection[]) => [...list].sort((a, b) => a.order - b.order);

/** The menu sections an agent may add: not hidden, and the list's own entries rather than the fixed fields. */
export const offeredSections = (list: readonly InstructionSection[]) => inOrder(list).filter((s) => s.kind === 'menu' && !s.hidden);

/** Why these sections cannot be saved, worded as the agents service words it; null when they can. */
export function sectionProblem(sections: readonly BriefSection[], list: readonly InstructionSection[], customMax: number): string | null {
  const labelOf = (kind: string) => list.find((s) => s.id === kind)?.label ?? kind;
  const menu = sections.filter((s) => s.kind !== CUSTOM_ID).map((s) => s.kind);
  const unknown = menu.find((k) => !list.some((s) => s.id === k && s.kind === 'menu'));
  if (unknown) return `brief.sections: ${unknown} is not a section this workspace offers.`;
  const twice = menu.find((k) => menu.filter((m) => m === k).length > 1);
  if (twice) return `brief.sections: ${labelOf(twice)} is added more than once. Keep one.`;
  const names = sections.filter((s) => s.kind === CUSTOM_ID).map((s) => s.name.trim());
  if (names.length > customMax) return `brief.sections: an agent may have at most ${customMax} sections of its own.`;
  const reserved = new Set([...list.map((s) => s.label), ...EXTRA_RESERVED].map(folded));
  const seen = new Set<string>();
  for (const name of names) {
    if (name.length > CUSTOM_NAME_MAX) return `brief.sections: a section's name is at most ${CUSTOM_NAME_MAX} characters.`;
    if (reserved.has(folded(name))) return `brief.sections: ${name} is a heading the brief already has. Pick another name.`;
    if (seen.has(folded(name))) return `brief.sections: two sections are named ${name}. Give each its own name.`;
    seen.add(folded(name));
  }
  return null;
}

/** A section as saved: a menu kind carries the list's label, a custom one its trimmed name. */
export const titled = (s: BriefSection, list: readonly InstructionSection[]): BriefSection => ({
  kind: s.kind,
  name: s.kind === CUSTOM_ID ? s.name.trim() : (list.find((i) => i.id === s.kind)?.label ?? s.name),
  text: s.text,
});

/** One place in the brief, in the order the list writes it: a field of the brief, or a section a builder added. */
export type Place = { at: 'field'; id: string; item: InstructionSection } | { at: 'section'; section: BriefSection; item?: InstructionSection; custom: number };

/**
 * The brief's places in the list's order. A menu section sits where its entry does (even a hidden one an agent
 * already holds), the builder's own sections where the `custom` entry does, in the order saved. A section whose entry
 * has gone from the list is written after the list's last entry. The never rules are not a place: they are written last.
 */
export function placesOf(list: readonly InstructionSection[], sections: readonly BriefSection[]): Place[] {
  const places: Place[] = [];
  let custom = 0;
  const used = new Set<BriefSection>();
  for (const item of inOrder(list)) {
    if (item.kind === 'fixed') {
      if (item.drives !== 'never-last') places.push({ at: 'field', id: item.id, item });
    } else if (item.id === CUSTOM_ID) {
      for (const s of sections.filter((x) => x.kind === CUSTOM_ID)) {
        used.add(s);
        places.push({ at: 'section', section: s, item, custom: custom++ });
      }
    } else {
      const s = sections.find((x) => x.kind === item.id);
      if (s) {
        used.add(s);
        places.push({ at: 'section', section: s, item, custom: 0 });
      }
    }
  }
  for (const s of sections.filter((x) => !used.has(x))) places.push({ at: 'section', section: s, custom: s.kind === CUSTOM_ID ? custom++ : 0 });
  return places;
}

/** The prompt text the service writes from a brief (the mock's copy of its writer): headings in list order, empty sections left out. */
export function composeHead(name: string, b: AgentBrief, list: readonly InstructionSection[]): string {
  const part = (heading: string, text: string) => (text.trim() ? [`# ${heading}\n${text.trim()}`] : []);
  const handOff = b.handOff.map((r) => r.trim()).filter(Boolean);
  return placesOf(list, b.sections ?? [])
    .flatMap((p) => {
      if (p.at === 'section') return part(p.section.kind === CUSTOM_ID ? p.section.name.trim() : (p.item?.label ?? p.section.name), p.section.text);
      switch (p.id) {
        case 'purpose':
          return [`# Who you are\nYou are ${name}.\nYour job: ${b.purpose.trim()}`];
        case 'goal':
          return part(p.item.label, b.goal);
        case 'how_to_answer':
          return part(p.item.label, b.howToAnswer);
        case 'hand_off':
          return handOff.length ? [`# ${p.item.label}\n${handOff.map((r) => `- ${r}`).join('\n')}`] : [];
        case 'examples':
          return part(p.item.label, b.examples);
        default:
          return [];
      }
    })
    .join('\n\n');
}
