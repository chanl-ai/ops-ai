'use client';

/**
 * An app's Resources tab, on the generated SDK through `sdk()`: the app's one list of resources with each row's state
 * for the team (tools-service joins the copies agents-service and documents-service keep), the preview of adding
 * several, the adds themselves, an update taken from the app, and a copy removed through its kind's own delete.
 *
 * An add that spans services runs here, in the preview's order, one service call per copy, each with its own checks:
 * no service acts in another. A copy made before a refused one stays an ordinary draft, and the outcome names it.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { ApiError } from '@/lib/api/contract';
import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';

import { useTeamQuery } from './team-query';

type Raw = OpsAI['raw'];
export type AppResource = Awaited<ReturnType<Raw['tools']['plugins_list_app_resources']>>[number];
export type ResourcePlan = Awaited<ReturnType<Raw['agents']['resources_plan_resources']>>;
export type PlanItem = ResourcePlan['items'][number];
export type UpdateReview = Awaited<ReturnType<Raw['agents']['resources_review_update']>>;
export type ResourceKind = AppResource['kind'];
/** A record that uses a copy, as a refused delete names it. */
export type CopyUser = { kind: string; id: string; name: string };

/** What the person fills in the preview: the knowledge base and model alias to bind, and names for clashing copies. */
export type AddBindings = { knowledgeBase?: string; modelAlias?: string; names: Record<string, string> };
/** One copy the add made (or the knowledge source it put in a base), or the refusal that stopped it. */
export type AddOutcome = { item: PlanItem; kind: ResourceKind; recordId?: string; error?: ApiError };

const key = (app: string) => ['app-resources', app] as const;

export const useAppResources = (app: string) =>
  useTeamQuery({
    queryKey: key(app),
    queryFn: () => sdk((ops) => ops.raw.tools.plugins_list_app_resources({ path: { app_id: app } })),
    enabled: !!app,
  });

/** The preview of adding these resources (each `<source>:<id>`): what they bring, what the team holds, what to fill. */
export const useResourcePlan = () =>
  useMutation({ mutationFn: (resources: string[]) => sdk((ops) => ops.raw.agents.resources_plan_resources({ body: { resources } })) });

const failure = (e: unknown) => (e instanceof ApiError ? e : new ApiError(e instanceof Error ? e.message : String(e), 0));

async function addOne(item: PlanItem, bindings: AddBindings, made: Record<string, string>): Promise<string> {
  const name = bindings.names[item.resource]?.trim() || undefined;
  const wants = (b: string) => item.bindings.some((x) => b in x);
  if (item.service === 'documents') {
    const answer = await sdk((ops) => ops.raw.documents.resources_copy_resource({ path: { resource: item.resource }, body: { name } }));
    return answer.copy.recordId;
  }
  if (item.service === 'kb') {
    if (!bindings.knowledgeBase) throw new ApiError(`Pick a knowledge base for ${item.title} first.`, 422);
    const [plugin, source] = [item.resource.split(':')[1] ?? '', item.resource.split(':').slice(2).join(':')];
    const created = await sdk((ops) =>
      ops.raw.kb.sources_create_source({
        body: { type: 'tool', name: item.title, config: { plugin, source }, kbIds: [bindings.knowledgeBase!], sync: true, collection: '', sensitivity: 'internal', tags: [], fileIds: [] },
      }),
    );
    return String((created as { id: string }).id);
  }
  const answer = await sdk((ops) =>
    ops.raw.agents.resources_copy_resource({
      path: { resource: item.resource },
      body: {
        name,
        knowledgeBases: wants('knowledgeBase') && bindings.knowledgeBase ? [bindings.knowledgeBase] : [],
        modelAlias: wants('modelAlias') ? bindings.modelAlias || undefined : undefined,
        // Document type copies documents-service made earlier in this add, so the workflow's steps name them.
        copies: made,
      },
    }),
  );
  return answer.copy.recordId;
}

/** Add selected (and Add to team, one item): every copy the plan needs, in its order; stops at the first refusal. */
export function useAddResources(app: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ plan, bindings }: { plan: ResourcePlan; bindings: AddBindings }): Promise<AddOutcome[]> => {
      const made: Record<string, string> = {};
      for (const i of plan.items) if (i.heldRecordId) made[i.resource] = i.heldRecordId;
      const out: AddOutcome[] = [];
      for (const item of plan.items) {
        if (item.heldRecordId) continue;
        try {
          const recordId = await addOne(item, bindings, made);
          made[item.resource] = recordId;
          out.push({ item, kind: item.kind, recordId });
        } catch (e) {
          out.push({ item, kind: item.kind, error: failure(e) });
          break;
        }
      }
      return out;
    },
    onSettled: () => Promise.all([qc.invalidateQueries({ queryKey: key(app) }), qc.invalidateQueries({ queryKey: ['templates'] })]),
  });
}

/** Review update: what the app's template would change in the copy, and the team's edits the new draft leaves out. */
export const useUpdateReview = (resource: string, copy: string | undefined) =>
  useTeamQuery({
    queryKey: ['app-resources', 'update', resource, copy],
    queryFn: () => sdk((ops) => ops.raw.agents.resources_review_update({ path: { resource, copy: copy! } })),
    enabled: !!copy,
  });

/** Take update: a new draft version of the copy; `confirm` says the person saw the edits it does not carry. */
export function useTakeUpdate(app: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ resource, copy, confirm }: { resource: string; copy: string; confirm: boolean }) =>
      sdk((ops) => ops.raw.agents.resources_take_update({ path: { resource, copy }, body: { confirm } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: key(app) }),
  });
}

/** Remove: the copy's own delete, which answers 409 in_use naming each record that uses it. */
export function useRemoveCopy(app: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, recordId }: { kind: ResourceKind; recordId: string }): Promise<unknown> => {
      if (kind === 'agent') return sdk((ops) => ops.raw.agents.agents_delete_agent({ path: { agent_id: recordId } }));
      if (kind === 'skill') return sdk((ops) => ops.raw.agents.agents_delete_skill({ path: { skill_id: recordId } }));
      if (kind === 'workflow') return sdk((ops) => ops.raw.agents.workflows_delete_definition({ path: { workflow_id: recordId } }));
      return sdk((ops) => ops.raw.documents.document_types_delete_type({ path: { type_id: recordId } }));
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: key(app) }),
  });
}

/** The records a refused delete names, from its `details.usedBy`. */
export const usersOf = (e: unknown): CopyUser[] =>
  e instanceof ApiError && e.code === 'in_use' && Array.isArray(e.details?.usedBy) ? (e.details.usedBy as CopyUser[]) : [];
