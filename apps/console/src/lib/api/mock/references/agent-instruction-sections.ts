import { ApiError } from '@/lib/api/contract';
import { slugify } from '@/lib/validation/names';
import type { InstructionSection, InstructionSectionList, PresetIcon, SectionPreset } from '@/lib/types/domain';

const PRESETS_MAX = 8;
const LABEL_MAX = 40;
const DRIVER: Record<string, InstructionSection['drives']> = { hand_off: 'handoff', never: 'never-last' };
const FIXED = ['purpose', 'goal', 'how_to_answer', 'hand_off', 'examples', 'never'];

const preset = (label: string, icon: PresetIcon, text: string): SectionPreset => ({ id: slugify(label, { sep: '_' }), label, icon, text });
const VOICES = (lines: [string, string, string, string, string]): SectionPreset[] =>
  (['Warm', 'Neutral', 'Formal', 'Concise', 'Plain-spoken'] as const).map((l, i) => preset(l, (['smile', 'scale', 'briefcase', 'zap', 'message'] as const)[i], lines[i]));

type Row = [id: string, label: string, kind: InstructionSection['kind'], hint: string, group: string, example: string];
// The default list in the order the prompt writes it, as the agents service serves it.
const ROWS: Row[] = [
  ['purpose', 'Purpose', 'fixed', 'What the agent is for, in one sentence.', '', 'Help customers dispute a card charge.'],
  ['goal', 'Goal', 'fixed', 'What a finished conversation achieves.', '', 'Every dispute is opened with the right charge.'],
  ['personality', 'Personality', 'menu', 'Who the agent is to the person it talks to.', 'Voice and style', 'Patient and steady.'],
  ['tone', 'Tone', 'menu', "How the agent's words sound, in one place.", 'Voice and style', 'Warm, plain words, no jargon.'],
  ['environment', 'Environment', 'menu', 'Where the agent works and who it talks to.', 'Context', "You answer in the bank's chat."],
  ['context', 'Context', 'menu', 'Facts the agent needs that are not in its knowledge.', 'Context', 'Disputes close after 120 days.'],
  ['how_to_answer', 'How to answer', 'fixed', 'What an answer holds and its format: length, structure, what to include.', '', 'Two short paragraphs at most.'],
  ['tool_use', 'Tool use', 'menu', 'When and how the agent uses its tools.', 'Behaviour', 'Read the charge before you answer.'],
  ['error_handling', 'Error handling', 'menu', 'What the agent does when a tool fails.', 'Behaviour', 'Say so and try once more.'],
  ['custom', 'Your own sections', 'custom', 'A section a builder names and writes; prompt text only.', '', 'Refund wording'],
  ['hand_off', 'Hand off when', 'fixed', 'When the agent passes the conversation to a person.', '', 'The person asks for a human.'],
  ['escalation', 'Escalation wording', 'menu', 'What the agent says as it hands off.', 'Behaviour', 'Say: I am passing you to a colleague.'],
  ['examples', 'Examples', 'fixed', 'A question and the answer you want.', '', 'Q: Is it fraud? A: Tell me the amount.'],
  ['never', 'Never', 'fixed', 'What the agent must never do; the prompt ends with these.', '', 'Never promise a refund date.'],
];
const PRESET_SETS: Record<string, SectionPreset[]> = {
  personality: VOICES([
    'You are warm and patient, and you treat each person as someone you want to help.',
    'You are even and factual, and you keep your own views out of your answers.',
    'You are courteous and professional, as a careful bank officer would be.',
    'You are direct and get to the point without small talk.',
    'You speak as a person would across a counter, in everyday words.',
  ]),
  tone: VOICES([
    'Use a friendly, encouraging tone and thank the person when they help you.',
    'Use a calm, neutral tone; state facts without emphasis.',
    'Use a formal tone: full sentences, no slang, no exclamation marks.',
    'Keep each reply short: one or two sentences unless the person asks for more.',
    'Use short, everyday words and explain any term the person may not know.',
  ]),
};

export const defaultSectionList = (): InstructionSectionList => ({
  customMax: 5,
  sections: ROWS.map(([id, label, kind, hint, group, example], order) => ({
    id,
    label,
    hint,
    kind,
    order,
    required: id === 'purpose',
    hidden: false,
    drives: DRIVER[id] ?? (kind === 'menu' ? 'eval-tag' : 'none'),
    group,
    example,
    presets: PRESET_SETS[id] ?? [],
  })),
});

const slug = (text: string) => slugify(text, { sep: '_', width: 37, fallback: 'section' });
const refused = (problem: string) => new ApiError(`sections: ${problem}`, 422, undefined, 'validation_failed');

/** The list as the service stores it: new entries get an id from their label, order renumbered, the service's rules held (422 otherwise). */
export function checkedSectionList(body: InstructionSectionList): InstructionSectionList {
  const sent = [...body.sections].sort((a, b) => a.order - b.order);
  const taken = new Set([...sent.map((s) => s.id).filter(Boolean), ...FIXED, 'custom']);
  const labels = new Set<string>();
  const items = sent.map((s, order): InstructionSection => {
    const id = s.id || (() => { let n = slug(s.label), i = 2; const base = n; while (taken.has(n)) n = `${base}_${i++}`; taken.add(n); return n; })();
    if (!s.label.trim() || s.label.trim().length > LABEL_MAX) throw refused(`a label is 1 to ${LABEL_MAX} characters.`);
    if ((FIXED.includes(id)) !== (s.kind === 'fixed') || (id === 'custom') !== (s.kind === 'custom')) throw refused(`${s.label} cannot change what kind of section it is.`);
    if (s.kind === 'fixed' && s.hidden) throw refused(`${s.label} is part of every brief and cannot be hidden.`);
    const wants = DRIVER[id];
    if (wants && s.drives !== wants) throw refused(`${s.label} drives ${wants}, and no other section can.`);
    const folded = s.label.split(/\s+/).filter(Boolean).join(' ').toLowerCase();
    if (labels.has(folded)) throw refused(`two sections are labelled ${s.label}. Give each its own label.`);
    labels.add(folded);
    if (s.presets.length > PRESETS_MAX) throw refused(`${s.label} has ${s.presets.length} presets; a section offers at most ${PRESETS_MAX}.`);
    const own = s.kind === 'menu' && !ROWS.some((r) => r[0] === id);
    return { ...s, id, label: s.label.trim(), order, group: s.group || (own ? 'Your sections' : ''), presets: s.presets.map((p) => ({ ...p, id: p.id || slug(p.label) })) };
  });
  const gone = [...FIXED, 'custom'].filter((id) => !items.some((s) => s.id === id));
  if (gone.length) throw refused(`${gone.join(', ')} ${gone.length === 1 ? 'is' : 'are'} part of every brief and cannot be removed.`);
  return { sections: items, customMax: body.customMax };
}
