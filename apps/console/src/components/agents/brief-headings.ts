import type { MenuSectionKind } from '@/lib/types/domain';

/** The words the page uses for a brief field a publish problem names. */
export const HEADING: Record<string, string> = { 'brief.purpose': 'Job', 'brief.goal': 'Goal', 'brief.howToAnswer': 'How to answer', 'brief.handOff': 'Hand off when', 'brief.examples': 'Examples', 'brief.never': 'Never', 'brief.success': 'Success checks', 'brief.sections': 'An added section' };

/** What each section from the Add section menu is for, as the hint in its empty text. */
export const SECTION_COPY: Record<MenuSectionKind, { placeholder: string }> = {
  personality: { placeholder: 'Who this agent is: its traits and manner. Type @ to name a tool, knowledge or skill.' },
  tone: { placeholder: 'How this agent sounds. Keep tone here and out of How to answer.' },
  environment: { placeholder: 'Where this agent works and who it talks to, e.g. a bank’s card desk, over chat.' },
  context: { placeholder: 'Facts this agent should know before it answers.' },
  tool_use: { placeholder: 'When this agent uses each tool, and what to do with what it returns. Type @ to name a tool.' },
  error_handling: { placeholder: 'What this agent does when a tool fails or it cannot find the answer.' },
  escalation: { placeholder: 'What this agent says as it hands the conversation to a person.' },
};

export const CUSTOM_PLACEHOLDER = 'Written into the prompt as it is. Type @ to name a tool, knowledge or skill.';
