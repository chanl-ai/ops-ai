'use client';

/**
 * A plugin update's review and take, on the generated SDK through `sdk()`: what taking the installed version
 * would change for the team, which of the team's agents and workflows use each changed or removed tool, and taking it.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';

import { useTeamQuery } from './team-query';

type Tools = OpsAI['raw']['tools'];
type Agents = OpsAI['raw']['agents'];

export type PluginUpdate = Awaited<ReturnType<Tools['apps_plugin_update']>>;
export type ToolChange = PluginUpdate['tools'][number];
export type ToolUses = Awaited<ReturnType<Agents['agents_list_tool_uses']>>;

const update = (appId: string) => ['apps', appId, 'update'] as const;

/** The review for one plugin's app (`plugin:<id>`): the team's version, the installed one, and each changed tool. Asked
 * only once the app's card says an update waits (`plugin.updateAvailable`), which is false while the install's
 * plugin_updates flag is off or the team has not turned the app on. */
export const usePluginUpdate = (appId: string) =>
  useTeamQuery({
    queryKey: update(appId),
    queryFn: () => sdk((ops) => ops.raw.tools.apps_plugin_update({ path: { app_id: appId } })),
  });

/** For each changed or removed tool, the team's agents and workflows that use it; nothing to ask when none changed. */
export const useToolUses = (tools: string[]) =>
  useTeamQuery({
    queryKey: ['tool-uses', ...tools],
    queryFn: () => sdk((ops) => ops.raw.agents.agents_list_tool_uses({ query: { tools: tools.join(',') } })),
    enabled: tools.length > 0,
  });

export type TemplateCopy = Awaited<ReturnType<Agents['templates_list_templates']>>[number];

/** The plugin's templates with the version of the team's copy of each (copy provenance), for the review. */
export const usePluginTemplates = (source: string) =>
  useTeamQuery({
    queryKey: ['templates', source],
    queryFn: () => sdk((ops) => ops.raw.agents.templates_list_templates({ query: { source } })),
    enabled: !!source,
  });

/** Takes the installed version with the digest the review was read at; a review replaced since is refused (409). */
export function useTakePluginUpdate(appId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (digest: string) => sdk((ops) => ops.raw.tools.apps_take_plugin_update({ path: { app_id: appId }, body: { digest } })),
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ['apps'] }), qc.invalidateQueries({ queryKey: ['systems'] })]),
  });
}

export type AccountUses = Awaited<ReturnType<Agents['workflows_account_uses']>>;

/** How many of the team's workflow drafts and published versions, and agents, name one account of an app: what the
 * rename and delete of that account warn with. Asked only while `enabled` (the dialog is open). */
export const useAccountUses = (app: string, name: string, enabled = true) =>
  useTeamQuery({
    queryKey: ['account-uses', app, name],
    queryFn: () => sdk((ops) => ops.raw.agents.workflows_account_uses({ query: { app, name } })),
    enabled: enabled && Boolean(app && name),
  });
