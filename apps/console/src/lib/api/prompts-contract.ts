import type {
  PromptAnalysis,
  PromptContext,
  PromptSection,
  PromptSpec,
  PromptStreamEvent,
  PromptVariable,
  RewriteSectionInput,
} from '@/lib/types/prompts';

/**
 * Prompt tooling (spec 12, ADR-0011): the instructions generator, lint and the variable list. Shared
 * instruction text is an always-on skill (spec 11). Generation and rewrites go through the AI gateway in production; nothing here saves an agent.
 */
export interface PromptsApi {
  variables(): Promise<PromptVariable[]>;
  /** Streams the generated instructions section by section. Aborting keeps nothing on the server. */
  generate(spec: PromptSpec, context: PromptContext, signal?: AbortSignal): AsyncIterable<PromptStreamEvent>;
  rewriteSection(input: RewriteSectionInput): Promise<PromptSection>;
  /** Token count, cost estimate and lint findings with fixes for a set of sections or plain instructions. */
  analyze(sections: PromptSection[], context: PromptContext): Promise<PromptAnalysis>;

}
