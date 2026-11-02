'use client';

/**
 * A plugin update's review and take (c-609), on the generated SDK through `sdk()`: what taking the installed version
 * would change for the team, which of the team's agents and workflows use each changed or removed tool, and taking it.
 * The routes answer 404 while the install's plugin_updates flag is off, so the screen shows nothing then.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';

import { useFlag } from './flag-queries';
import { useTeamQuery } from './team-query';

type Tools = OpsAI['raw']['tools'];
type Agents = OpsAI['raw']['agents'];

export type PluginUpdate = Awaited<ReturnType<Tools['plugins_plugin_update']>>;
export type ToolChange = PluginUpdate['tools'][number];
export type ToolUses = Awaited<ReturnType<Agents['agents_list_tool_uses']>>;

const update = (pluginId: string) => ['plugins', pluginId, 'update'] as const;

/** The review for one plugin: the team's version, the installed one, and each new, changed and removed tool. */
export const usePluginUpdate = (pluginId: string) => {
  // The route answers 404 while the install's plugin_updates flag is off; asking then only logs a 404 on every app page.
  const on = useFlag('plugin_updates');
  return useTeamQuery({
    queryKey: update(pluginId),
    queryFn: () => sdk((ops) => ops.raw.tools.plugins_plugin_update({ path: { plugin_id: pluginId } })),
    enabled: on,
  });
};

/** For each changed or removed tool, the team's agents and workflows that use it; nothing to ask when none changed. */
export const useToolUses = (tools: string[]) =>
  useTeamQuery({
    queryKey: ['tool-uses', ...tools],
    queryFn: () => sdk((ops) => ops.raw.agents.agents_list_tool_uses({ query: { tools: tools.join(',') } })),
    enabled: tools.length > 0,
  });

export type TemplateCopy = Awaited<ReturnType<Agents['templates_list_templates']>>[number];

/** The plugin's templates with the version of the team's copy of each (copy provenance, c-590), for the review. */
type Documents = OpsAI['raw']['documents'];
export type DocumentTypeTemplate = Awaited<ReturnType<Documents['templates_list_templates']>>[number];
/**
 * The plugin's document types with the team's copies of each, from documents-service (U5). Its list takes no source, so
 * the installed plugins' few document types are narrowed to this plugin's here.
 */
export const usePluginDocumentTypes = (source: string) =>
  useTeamQuery({
    queryKey: ['templates', 'documents', source],
    queryFn: async () => (await sdk((ops) => ops.raw.documents.templates_list_templates({ query: {} }))).filter((t) => t.source === source),
    enabled: !!source,
  });
/**
 * Add to team (U5): the team's own copy of one resource an app brings, made by the service that keeps that kind
 * (POST /v1/resources/{source}:{id}/copies). Asking again answers the copy already made, so Open uses it too.
 */
export function useCopyResource(source: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, service }: { id: string; service: 'agents' | 'documents' }): Promise<{ copy: { kind: 'agent' | 'skill' | 'workflow' | 'document_type'; recordId: string } }> =>
      service === 'documents'
        ? sdk((ops) => ops.raw.documents.resources_copy_resource({ path: { resource: `${source}:${id}` }, body: {} }))
        : sdk((ops) => ops.raw.agents.resources_copy_resource({ path: { resource: `${source}:${id}` }, body: {} })),
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ['templates', source] }), qc.invalidateQueries({ queryKey: ['templates', 'documents', source] })]),
  });
}
export const usePluginTemplates = (source: string) =>
  useTeamQuery({
    queryKey: ['templates', source],
    queryFn: () => sdk((ops) => ops.raw.agents.templates_list_templates({ query: { source } })),
    enabled: !!source,
  });

/** Takes the installed version with the digest the review was read at; a review replaced since is refused (409). */
export function useTakePluginUpdate(pluginId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (digest: string) =>
      sdk((ops) => ops.raw.tools.plugins_take_plugin_update({ path: { plugin_id: pluginId }, body: { digest } })),
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: update(pluginId) }), qc.invalidateQueries({ queryKey: ['plugins'] })]),
  });
}
