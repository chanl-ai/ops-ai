'use client';

import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { usePagedQuery } from '@/hooks/paged-query';
import { api } from '@/lib/api';
import type { ListParams } from '@/lib/types/query';
import type {
  GeneratedSkill,
  SkillCreateInput,
  SkillDraftForCheck,
  SkillCandidateScope,
  SkillDraftPatch,
  SkillFilters,
  SkillGenerateInput,
  SkillRewriteInput,
  SkillSectionKey,
  SkillTestCaseInput,
  SkillView,
} from '@/lib/types/skills';

/** Every skill key starts with 'skills'; an agent's skills sit under the agent key so attaching refreshes the agent. */
export const sk = {
  list: (p: unknown) => ['skills', 'list', p] as const,
  one: (id: string) => ['skills', 'one', id] as const,
  options: ['skills', 'options'] as const,
  generateOptions: ['skills', 'generate-options'] as const,
  importPreview: (fileId: string) => ['skills', 'import', fileId] as const,
  agent: (agentId: string) => ['agent', agentId, 'skills'] as const,
  candidates: (scope: unknown) => ['skills', 'candidates', scope] as const,
};

export const useSkills = (p: ListParams<SkillFilters> & { view: SkillView }) => usePagedQuery({ queryKey: sk.list(p), queryFn: () => api.skills.list(p) });
export const useSkill = (id: string) => useQuery({ queryKey: sk.one(id), queryFn: () => api.skills.get(id) });
export const useSkillOptions = () => useQuery({ queryKey: sk.options, queryFn: api.skills.options, staleTime: 60_000 });
export const useSkillGenerateOptions = (enabled: boolean) => useQuery({ queryKey: sk.generateOptions, queryFn: api.skills.generateOptions, enabled, staleTime: 30_000 });
export const useSkillImportPreview = (fileId: string | undefined) => useQuery({ queryKey: sk.importPreview(fileId ?? ''), queryFn: () => api.skills.previewImport(fileId!), enabled: !!fileId, retry: false });
/** Skills a new agent could pin; `scope` is null until the wizard knows the owner, tools and knowledge bases. */
export const useSkillCandidates = (scope: SkillCandidateScope | null) => usePagedQuery({ queryKey: sk.candidates(scope), queryFn: () => api.skills.candidates(scope!), enabled: !!scope });
export const useAgentSkills = (agentId: string) => useQuery({ queryKey: sk.agent(agentId), queryFn: () => api.skills.agents.get(agentId) });

/** Skill writes can open reviews, change agents and always write the audit log, so those refresh too. */
function useSkillWrite<A, R>(fn: (a: A) => Promise<R>, also: string[] = []) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => Promise.all(['skills', 'reviews', 'logs', 'files', ...also].map((r) => qc.invalidateQueries({ queryKey: [r] }))) });
}

export const useCreateSkill = () => useSkillWrite((i: SkillCreateInput) => api.skills.create(i));
export const useSaveSkillDraft = (id: string) => useSkillWrite((p: SkillDraftPatch) => api.skills.saveDraft(id, p));
export const useRestoreSkill = (id: string) => useSkillWrite((v: number) => api.skills.restore(id, v));
export const useDuplicateSkill = () => useSkillWrite((id: string) => api.skills.duplicate(id));
export const useRequestSkillReview = (id: string) => useSkillWrite((note: string) => api.skills.requestReview(id, note), ['notifications']);
export const useDeprecateSkill = (id: string) => useSkillWrite((reason: string) => api.skills.deprecate(id, reason), ['agent']);
export const useDeleteSkill = () => useSkillWrite((id: string) => api.skills.remove(id), ['agent']);
export const useBulkDeprecateSkills = () => useSkillWrite(({ ids, reason }: { ids: string[]; reason: string }) => api.skills.bulkDeprecate(ids, reason), ['agent']);
export const useBulkDeleteSkills = () => useSkillWrite((ids: string[]) => api.skills.bulkRemove(ids), ['agent']);
export const useExportSkills = () => useSkillWrite(({ ids, version }: { ids: string[]; version?: number }) => api.skills.exportSkills(ids, version));
export const useImportSkill = () => useSkillWrite(({ fileId, ownerTeam }: { fileId: string; ownerTeam: string }) => api.skills.importSkill(fileId, ownerTeam));
export const useAddSkillTest = (id: string) => useSkillWrite((i: SkillTestCaseInput) => api.skills.tests.add(id, i));
export const useUpdateSkillTest = (id: string) => useSkillWrite(({ caseId, input }: { caseId: string; input: SkillTestCaseInput }) => api.skills.tests.update(id, caseId, input));
export const useRemoveSkillTest = (id: string) => useSkillWrite((caseId: string) => api.skills.tests.remove(id, caseId));
export const useRunSkillTests = (id: string) => useSkillWrite(() => api.skills.tests.run(id));
export const useAddSkillResource = (id: string) => useSkillWrite((i: { fileIds?: string[]; template?: { name: string; body: string } }) => api.skills.resources.add(id, i));
export const useRemoveSkillResource = (id: string) => useSkillWrite((resourceId: string) => api.skills.resources.remove(id, resourceId));

export const useAttachSkill = (agentId: string) => useSkillWrite(({ skillId, version }: { skillId: string; version?: number }) => api.skills.agents.attach(agentId, skillId, version), ['agent', 'agents']);
/** Moves one agent's pin from the skill page's Used by tab. */
export const useMoveSkillPin = () => useSkillWrite(({ agentId, skillId, version }: { agentId: string; skillId: string; version: number }) => api.skills.agents.attach(agentId, skillId, version), ['agent', 'agents']);
export const useDetachSkill = (agentId: string) => useSkillWrite((skillId: string) => api.skills.agents.detach(agentId, skillId), ['agent', 'agents']);

/** Generation helpers: nothing here is stored until the dialog saves. */
export const useRewriteSection = () => useMutation({ mutationFn: (i: SkillRewriteInput) => api.skills.rewriteSection(i) });
export const useSuggestSkillTests = () => useMutation({ mutationFn: ({ input, skill }: { input: SkillGenerateInput; skill: GeneratedSkill }) => api.skills.suggestTests(input, skill) });
export const useSkillDryRun = () => useMutation({ mutationFn: ({ draft, tests }: { draft: SkillDraftForCheck; tests: SkillTestCaseInput[] }) => api.skills.dryRun(draft, tests) });
export const useSkillImpact = () => useMutation({ mutationFn: ({ draft, agentIds }: { draft: SkillDraftForCheck; agentIds: string[] }) => api.skills.impact(draft, agentIds) });

/** Everything the Generate skill dialog calls, so the dialog takes it as a prop and stays free of data hooks. */
export function useSkillGeneratorBackend(open: boolean) {
  return {
    options: useSkillGenerateOptions(open),
    generation: useSkillGeneration(),
    rewrite: useRewriteSection(),
    suggestTests: useSuggestSkillTests(),
    dryRun: useSkillDryRun(),
    impact: useSkillImpact(),
    create: useCreateSkill(),
  };
}
export type SkillGeneratorBackend = ReturnType<typeof useSkillGeneratorBackend>;

export type GenerationPhase ='idle' | 'streaming' | 'done' | 'stopped' | 'error';

export interface GenerationState {
  phase: GenerationPhase;
  status: string;
  name: string;
  useWhen: string;
  sections: Record<SkillSectionKey, string>;
  skill: GeneratedSkill | null;
  error: string | null;
}

const EMPTY_SECTIONS: Record<SkillSectionKey, string> = { steps: '', rules: '', examples: '', output_format: '' };
const IDLE: GenerationState = { phase: 'idle', status: '', name: '', useWhen: '', sections: EMPTY_SECTIONS, skill: null, error: null };

/**
 * Streams a drafted skill. Stop keeps what arrived so far on screen but marks it incomplete; Regenerate starts over.
 * Unmounting aborts the request.
 */
export function useSkillGeneration() {
  const [state, setState] = React.useState<GenerationState>(IDLE);
  const ctrl = React.useRef<AbortController | null>(null);
  React.useEffect(() => {
    const c = ctrl;
    return () => c.current?.abort();
  }, []);

  const start = React.useCallback(async (input: SkillGenerateInput) => {
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    setState({ ...IDLE, phase: 'streaming', status: 'Starting…', sections: { ...EMPTY_SECTIONS } });
    try {
      for await (const e of api.skills.generate(input, c.signal)) {
        if (c.signal.aborted) return;
        if (e.type === 'status') setState((s) => ({ ...s, status: e.text }));
        else if (e.type === 'field') setState((s) => ({ ...s, [e.field]: e.value }));
        else if (e.type === 'section') setState((s) => ({ ...s, status: 'Writing…', sections: { ...s.sections, [e.section]: s.sections[e.section] + e.delta } }));
        else if (e.type === 'done') setState((s) => ({ ...s, phase: 'done', status: '', skill: e.skill, sections: e.skill.sections, name: e.skill.name, useWhen: e.skill.useWhen }));
        else if (e.type === 'error') setState((s) => ({ ...s, phase: 'error', error: e.message }));
      }
    } catch (e) {
      if (!c.signal.aborted) setState((s) => ({ ...s, phase: 'error', error: (e as Error).message }));
    }
  }, []);

  const stop = React.useCallback(() => {
    ctrl.current?.abort();
    setState((s) => (s.phase === 'streaming' ? { ...s, phase: 'stopped', status: '' } : s));
  }, []);
  const reset = React.useCallback(() => {
    ctrl.current?.abort();
    setState(IDLE);
  }, []);

  return { state, start, stop, reset };
}
