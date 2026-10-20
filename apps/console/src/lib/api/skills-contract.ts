import type { BulkResult } from '@/lib/types/domain';
import type { FileRecord } from '@/lib/types/files';
import type { ListParams, ListResult, OptionsPage, OptionsParams } from '@/lib/types/query';
import type {
  SkillLoading,
  AgentSkills,
  GeneratedSkill,
  Skill,
  SkillCreateInput,
  SkillDetail,
  SkillDraftForCheck,
  SkillDraftPatch,
  SkillFilters,
  SkillGenerateEvent,
  SkillGenerateInput,
  SkillGenerateOptions,
  SkillImpact,
  SkillImportPreview,
  SkillOptions,
  SkillRewriteInput,
  SkillCandidates,
  SkillCandidateScope,
  SkillTestCase,
  SkillTestCaseInput,
  SkillTestRun,
  SkillView,
  SkillViewCounts,
} from '@/lib/types/skills';

/**
 * Skills (spec 11). Publishing goes through the Reviews queue as a `skill_publish` review decided by someone other
 * than the requester. Generation and rewrites are model calls through the AI gateway; their output is always a
 * draft. Create, generate, publish, deprecate, attach and detach write the audit log.
 */
export interface SkillsApi {
  list(params: ListParams<SkillFilters> & { view: SkillView }): Promise<ListResult<Skill> & { viewCounts: SkillViewCounts }>;
  get(id: string): Promise<SkillDetail>;
  create(input: SkillCreateInput): Promise<Skill>;
  /** Edits the newest draft, or opens one on top of the published version. 409 when `baseVersion` is stale. */
  saveDraft(id: string, patch: SkillDraftPatch): Promise<SkillDetail>;
  /** Copies a version into a new draft; nothing is published. */
  restore(id: string, version: number): Promise<SkillDetail>;
  duplicate(id: string): Promise<Skill>;
  /** 422 with the blockers when the newest version cannot be requested (no tests, never run, not a draft). */
  requestReview(id: string, note: string): Promise<SkillDetail>;
  /** Agents pinning it keep their version; new attaches are refused. */
  deprecate(id: string, reason: string): Promise<SkillDetail>;
  remove(id: string): Promise<void>;
  bulkDeprecate(ids: string[], reason: string): Promise<BulkResult>;
  /** Refused per skill while a live agent pins it. */
  bulkRemove(ids: string[]): Promise<BulkResult>;
  /** One zip of SKILL.md folders, stored through the Files API. */
  exportSkills(ids: string[], version?: number): Promise<FileRecord>;

  tests: {
    add(id: string, input: SkillTestCaseInput): Promise<SkillTestCase>;
    update(id: string, caseId: string, input: SkillTestCaseInput): Promise<SkillTestCase>;
    remove(id: string, caseId: string): Promise<void>;
    /** Runs every case on the newest version. */
    run(id: string): Promise<SkillTestRun>;
  };

  resources: {
    /** Files must be uploaded through the Files API first; a template is text kept on the version. */
    add(id: string, input: { fileIds?: string[]; template?: { name: string; body: string } }): Promise<SkillDetail>;
    remove(id: string, resourceId: string): Promise<SkillDetail>;
  };

  /** Streams a drafted skill from the start material and scope. Aborting keeps nothing. */
  generate(input: SkillGenerateInput, signal?: AbortSignal): AsyncIterable<SkillGenerateEvent>;
  rewriteSection(input: SkillRewriteInput): Promise<{ text: string; gatewayCallId: string }>;
  /** Drafts test cases from the generated skill and its sources. */
  suggestTests(input: SkillGenerateInput, skill: GeneratedSkill): Promise<SkillTestCaseInput[]>;
  /** Runs cases against an unsaved draft. Nothing is stored. */
  dryRun(draft: SkillDraftForCheck, tests: SkillTestCaseInput[]): Promise<SkillTestRun>;
  impact(draft: SkillDraftForCheck, agentIds: string[]): Promise<SkillImpact[]>;
  generateOptions(): Promise<SkillGenerateOptions>;
  options(): Promise<SkillOptions>;
  /** Published skills an agent with this scope could pin, for creating an agent from a template. */
  candidates(scope: SkillCandidateScope): Promise<SkillCandidates>;

  /** Reads an uploaded SKILL.md or folder zip. */
  previewImport(fileId: string): Promise<SkillImportPreview>;
  importSkill(fileId: string, ownerTeam: string): Promise<Skill>;

  agents: {
    get(agentId: string): Promise<AgentSkills>;
    /** Attaches or moves the pin; saves a new agent version. 422 when the agent lacks a tool or knowledge base the version needs. */
    /** `version` omitted attaches the latest published one, as the picker offers it. */
    attach(agentId: string, skillId: string, version?: number): Promise<AgentSkills>;
    /** The skill picker: published skills the agent does not hold, searched on the server; one needing access the agent lacks is disabled with the reason (c-136). */
    options(agentId: string, p: OptionsParams, loading?: SkillLoading): Promise<OptionsPage>;
    detach(agentId: string, skillId: string): Promise<AgentSkills>;
  };
}
