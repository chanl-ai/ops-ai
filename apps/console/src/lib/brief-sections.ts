import type { AgentBrief, BriefSection, BriefSectionKind, MenuSectionKind } from '@/lib/types/domain';

/** The heading each section from the Add section menu is written under, in the order the menu lists them. */
export const SECTION_TITLES: Record<MenuSectionKind, string> = {
  personality: 'Personality',
  tone: 'Tone',
  environment: 'Environment',
  context: 'Context',
  tool_use: 'Tool use',
  error_handling: 'Error handling',
  escalation: 'Escalation wording',
};
export const MENU_KINDS = Object.keys(SECTION_TITLES) as MenuSectionKind[];

export const CUSTOM_MAX = 5;
export const CUSTOM_NAME_MAX = 40;
/** Headings a section of the builder's own may not take: the brief writes them itself or keeps them for old versions. */
export const RESERVED_NAMES = ['Job', 'Purpose', 'Who you are', 'Goal', 'How to answer', 'Hand off when', 'Examples', 'Never', 'Success checks', ...Object.values(SECTION_TITLES)];

const folded = (name: string) => name.split(/\s+/).filter(Boolean).join(' ').toLowerCase();

/** Why these sections cannot be saved, worded as the agents service words it; null when they can. */
export function sectionProblem(sections: readonly BriefSection[]): string | null {
  const menu = sections.filter((s) => s.kind !== 'custom').map((s) => s.kind as MenuSectionKind);
  const twice = menu.find((k) => menu.filter((m) => m === k).length > 1);
  if (twice) return `brief.sections: ${SECTION_TITLES[twice]} is added more than once. Keep one.`;
  const names = sections.filter((s) => s.kind === 'custom').map((s) => s.name.trim());
  if (names.length > CUSTOM_MAX) return `brief.sections: an agent may have at most ${CUSTOM_MAX} sections of its own.`;
  const reserved = new Set(RESERVED_NAMES.map(folded));
  const seen = new Set<string>();
  for (const name of names) {
    if (name.length > CUSTOM_NAME_MAX) return `brief.sections: a section's name is at most ${CUSTOM_NAME_MAX} characters.`;
    if (reserved.has(folded(name))) return `brief.sections: ${name} is a heading the brief already has. Pick another name.`;
    if (seen.has(folded(name))) return `brief.sections: two sections are named ${name}. Give each its own name.`;
    seen.add(folded(name));
  }
  return null;
}

/** A section as saved: a menu kind carries its fixed title, a custom one its trimmed name. */
export const titled = (s: BriefSection): BriefSection => ({ kind: s.kind, name: s.kind === 'custom' ? s.name.trim() : SECTION_TITLES[s.kind], text: s.text });

// Where each menu section sits among the brief's own headings, as the service writes the prompt.
const BEFORE_HOW = ['personality', 'tone', 'environment', 'context'] as const;
const AFTER_HOW = ['tool_use', 'error_handling'] as const;

/** The sections in the order the prompt writes them, split around How to answer and Hand off when. */
export function placeSections(sections: readonly BriefSection[]) {
  const kind = (k: BriefSectionKind) => sections.filter((s) => s.kind === k);
  return {
    beforeHow: BEFORE_HOW.flatMap(kind),
    afterHow: [...AFTER_HOW.flatMap(kind), ...kind('custom')],
    afterHandOff: kind('escalation'),
  };
}

/** The prompt text the service writes from a brief (the mock's copy of `head`): headings in order, empty sections left out. */
export function composeHead(name: string, b: AgentBrief): string {
  const { beforeHow, afterHow, afterHandOff } = placeSections(b.sections ?? []);
  const part = (s: BriefSection) => (s.text.trim() ? [`# ${s.name.trim()}\n${s.text.trim()}`] : []);
  const handOff = b.handOff.map((r) => r.trim()).filter(Boolean);
  return [
    `# Who you are\nYou are ${name}.\nYour job: ${b.purpose.trim()}`,
    ...(b.goal.trim() ? [`# Goal\n${b.goal.trim()}`] : []),
    ...beforeHow.flatMap(part),
    ...(b.howToAnswer.trim() ? [`# How to answer\n${b.howToAnswer.trim()}`] : []),
    ...afterHow.flatMap(part),
    ...(handOff.length ? [`# Hand off when\n${handOff.map((r) => `- ${r}`).join('\n')}`] : []),
    ...afterHandOff.flatMap(part),
    ...(b.examples.trim() ? [`# Examples\n${b.examples.trim()}`] : []),
  ].join('\n\n');
}
