import type { SkillPartContent } from '@/lib/types/skills';

/** What the instructions editor edits, and how a skill's parts are drawn. */
export interface SkillBody {
  /** `text` for a skill written as steps; `instructions` for one with parts, whose shared introduction it is. */
  field: 'text' | 'instructions';
  /** Parts are read-only links under the instructions; each becomes its own skill, and none are added here. */
  parts: readonly SkillPartContent[];
}

/**
 * Every skill opens on the same instructions editor. A skill with parts keeps them (they are sent back unchanged, so
 * a save never drops them) but edits only its shared introduction there: the service refuses steps and parts together.
 */
export function skillBody(form: { parts: SkillPartContent[] }): SkillBody {
  return { field: form.parts.length ? 'instructions' : 'text', parts: form.parts };
}
