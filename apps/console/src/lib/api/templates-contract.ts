import type { ListParams, ListResult } from '@/lib/types/query';
import type {
  AgentTemplate,
  AgentTemplateDetail,
  CreateFromTemplateInput,
  CreateFromTemplateResult,
  TemplateFilters,
  TemplateSubmissionInput,
} from '@/lib/types/templates';

/** Agent templates (spec 12 §4.1). Owned by the platform team; teams submit agents for review. */
export interface TemplatesApi {
  /** Published templates, plus the current team's own submissions. */
  list(params: ListParams<TemplateFilters>): Promise<ListResult<AgentTemplate>>;
  /** The latest version, with what is missing in this workspace for the current team. */
  get(id: string): Promise<AgentTemplateDetail>;
  /** 409 when the handle is taken; 403 when a chosen tool is outside the team's grants. */
  createAgent(input: CreateFromTemplateInput): Promise<CreateFromTemplateResult>;
  /** Freezes the agent's current version into a submission for the platform team. */
  submit(input: TemplateSubmissionInput): Promise<AgentTemplate>;
}
