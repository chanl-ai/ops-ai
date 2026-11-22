/**
 * What a conversation says about its stepped skills, read from the replies' `skillRun` records. The Runtime decides
 * where a skill is, how it ended and in which reply; nothing here works that out by comparing replies.
 */
import type { ChatMessage, SkillRun } from '@/lib/types/chat';

export type SkillEnding = SkillRun['history'][number];

/** The skill running after the newest reply that is not still being written, or null. */
export function newestRun(messages: readonly ChatMessage[], writingId?: string): SkillRun | null {
  const replies = messages.filter((m) => m.role === 'assistant' && m.id !== writingId);
  return replies[replies.length - 1]?.skillRun ?? null;
}

/** The endings the server marks as belonging to this reply. Later replies repeat the record without the mark. */
export const endedInReply = (message: ChatMessage): SkillEnding[] => message.skillRun?.history.filter((h) => h.inReply === true) ?? [];

/** One ending as a sentence. It names the skill and the step, never a tool: hold data carries internal tool names. */
export function endingText(e: SkillEnding): string {
  if (e.ended === 'done') return `${e.name} finished`;
  if (e.ended === 'switched') return `${e.name} set aside`;
  if (e.why === 'denied') return `${e.name} stopped at step ${e.atStep}: a reviewer rejected the action`;
  if (e.ended === 'failed') return `${e.name} stopped at step ${e.atStep}${e.why === 'check' ? ': its check did not pass' : ''}`;
  return `${e.name} ended as ${e.ended} at step ${e.atStep}${e.meaning ? `: ${e.meaning}` : ''}`;
}

/** The skills whose actions are on hold after the newest reply, as one sentence; null when nothing is held. */
export function holdsText(run: SkillRun | null | undefined): string | null {
  const names = [...new Set((run?.holds ?? []).map((h) => h.name))];
  return names.length ? `Some actions are on hold until ${names.join(' and ')} starts again` : null;
}
