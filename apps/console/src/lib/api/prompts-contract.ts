import type { PromptVariable } from '@/lib/types/prompts';

/** Prompt tooling: the variable list `{{` offers. A brief is drafted on the agent (`agents.draftBrief`). */
export interface PromptsApi {
  variables(): Promise<PromptVariable[]>;
}
