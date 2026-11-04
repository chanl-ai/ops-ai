'use client';

/**
 * The real-connections screens' reads and writes, on the generated SDK through `sdk()` (lib/api/ops-sdk.ts):
 * the systems grid, a connection's keys per environment, a plugin's own app per environment, binding a module to its
 * connection, the team's sending policy and an operation's mock answers. Types come from the SDK's operations, so a
 * route change shows here as a type error, not as a broken screen.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';

import { useTeamQuery } from './team-query';

type Tools = OpsAI['raw']['tools'];
type Args<K extends keyof Tools> = NonNullable<Parameters<Tools[K]>[0]>;
type Data<K extends keyof Tools> = Awaited<ReturnType<Tools[K]>>;

export type SystemCard = Data<'connections_list_systems'>[number];
export type ConnectionDetail = Data<'connections_get_connection'>;
export type PluginView = Data<'plugins_list_plugins'>['plugins'][number];
export type SendPolicy = Data<'send_policy_get_send_policy'>;
export type TeamPluginBody = NonNullable<Args<'plugins_set_team_plugin'>['body']>;
export type MockAnswer = Data<'tool_modules_list_mocks'>['data'][number];

const SYSTEMS = ['systems'] as const;
const CONNECTIONS = ['connections'] as const;
const APPS = ['apps'] as const;

export const useSystems = () =>
  useTeamQuery({ queryKey: SYSTEMS, queryFn: () => sdk((ops) => ops.raw.tools.connections_list_systems()) });
export const usePlugins = () =>
  useTeamQuery({ queryKey: ['plugins'], queryFn: () => sdk((ops) => ops.raw.tools.plugins_list_plugins()) });

function useSystemsMutation<I, O>(fn: (i: I) => Promise<O>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () =>
      Promise.all([qc.invalidateQueries({ queryKey: SYSTEMS }), qc.invalidateQueries({ queryKey: CONNECTIONS }), qc.invalidateQueries({ queryKey: APPS })]),
  });
}

export type ConnectionKinds = Data<'connections_kinds'>;
/** The routes' environment parameter. The console holds environments as the ids GET /v1/connection-kinds lists. */
type ApiEnvironment = NonNullable<Args<'connections_test_connection'>['body']>['environment'];
const env = (id: string) => id as ApiEnvironment;

export type AppPage = Data<'connections_get_app'>;
/** One app's page, joined by tools-service: card, account, your own sign-in, tools, skills and latest runs. */
export const useApp = (appId: string) =>
  useTeamQuery({ queryKey: [...APPS, appId], queryFn: () => sdk((ops) => ops.raw.tools.connections_get_app({ path: { app_id: appId } })) });
/** Disconnect: ends the caller's own sign-in on a connection's environment (DELETE /v1/me/connections/{id}); the team's stays. */
export const useSignOutMine = () =>
  useSystemsMutation((a: { connectionId: string; environment: string }) =>
    sdk((ops) => ops.raw.tools.connections_disconnect({ path: { connection_id: a.connectionId }, query: { environment: env(a.environment) } })),
  );

export const useConnectionKinds = () =>
  useTeamQuery({ queryKey: ['connection-kinds'], queryFn: () => sdk((ops) => ops.raw.tools.connections_kinds()), staleTime: 5 * 60_000 });
export const useConnectionDetail = (connectionId: string | null | undefined) =>
  useTeamQuery({
    queryKey: [...CONNECTIONS, connectionId],
    queryFn: () => sdk((ops) => ops.raw.tools.connections_get_connection({ path: { connection_id: connectionId ?? '' } })),
    enabled: Boolean(connectionId),
  });

/** The team's connections a module may sign in through, for the connection picker. */
export const useConnectionOptions = (enabled = true) =>
  useTeamQuery({
    queryKey: [...CONNECTIONS, 'options'],
    queryFn: () => sdk((ops) => ops.raw.tools.connections_list_connections({ query: { pageSize: 100 } })),
    enabled,
  });

export const useCreateConnection = () =>
  useSystemsMutation((body: Args<'connections_create_connection'>['body']) => sdk((ops) => ops.raw.tools.connections_create_connection({ body })));
export const useSetEnvironment = () =>
  useSystemsMutation((a: { connectionId: string; environment: string; body: Args<'connections_set_environment'>['body'] }) =>
    sdk((ops) => ops.raw.tools.connections_set_environment({ path: { connection_id: a.connectionId, environment: env(a.environment) }, body: a.body })),
  );
export const useDeleteConnection = () =>
  useSystemsMutation((connectionId: string) => sdk((ops) => ops.raw.tools.connections_delete_connection({ path: { connection_id: connectionId } })));
export const useChangeConnection = () =>
  useSystemsMutation((a: Args<'connections_change_connection'>) => sdk((ops) => ops.raw.tools.connections_change_connection(a)));
/** Tests one environment with the team's account or the person's own; the answer is the connection with its health. */
export const useTestEnvironment = () =>
  useSystemsMutation((a: { connectionId: string; environment: string; account?: 'team' | 'self' }) =>
    sdk((ops) =>
      ops.raw.tools.connections_test_connection({
        path: { connection_id: a.connectionId },
        body: { environment: env(a.environment), account: a.account ?? 'team' },
      }),
    ),
  );
export const useStartSignIn = () =>
  useMutation({
    mutationFn: (a: { connectionId: string; environment: string; account: 'team' | 'self' }) =>
      sdk((ops) =>
        ops.raw.tools.connections_start_sign_in({ path: { connection_id: a.connectionId }, body: { environment: env(a.environment), account: a.account } }),
      ),
  });
export const useBindModule = () =>
  useSystemsMutation((a: { moduleId: string; connectionId: string | null }) =>
    sdk((ops) => ops.raw.tools.tool_modules_set_connection({ path: { module_id: a.moduleId }, body: { connectionId: a.connectionId } })),
  );
/**
 * The agents and workflows using an app's tools in the team (GET /v1/plugins/{id}/team/users), read when Turn off asks;
 * admins only. A 503 tool_users_unavailable means the service could not tell, which is an error, never "nothing".
 */
export const useAppUsers = (pluginId: string | null) =>
  useTeamQuery({ queryKey: [...SYSTEMS, 'users', pluginId], queryFn: () => sdk((ops) => ops.raw.tools.plugins_app_users({ path: { plugin_id: pluginId ?? '' } })), enabled: !!pluginId, retry: false });
/**
 * One OAuth client an app signs in with (GET /v1/app-credentials, team admins only): Ops AI's own app or the team's,
 * its permissions, how many accounts signed in through it, and its state from the last Test with my account.
 */
export type AppCredential = Data<'connections_list_app_credentials'>[number];
export const useAppCredentials = () =>
  useTeamQuery({ queryKey: [...SYSTEMS, 'app-credentials'], queryFn: () => sdk((ops) => ops.raw.tools.connections_list_app_credentials()) });
/** Replaces the client secret of the team's own app for a plugin (PUT /v1/plugins/{id}/app-secret); sealed on save. */
export const useSetAppSecret = () => useSystemsMutation((a: Args<'plugins_set_app_secret'>) => sdk((ops) => ops.raw.tools.plugins_set_app_secret(a)));
export const useSetTeamPlugin = () => useSystemsMutation((a: Args<'plugins_set_team_plugin'>) => sdk((ops) => ops.raw.tools.plugins_set_team_plugin(a)));
/** Another named account of an app the team has connected (several_accounts); answers the new account. */
export const useAddAccount = () => useSystemsMutation((a: Args<'plugins_add_account'>) => sdk((ops) => ops.raw.tools.plugins_add_account(a)));
/** Makes one of the app's accounts the caller's default: their calls that name no account use it. */
export const usePinDefault = () =>
  useSystemsMutation((connectionId: string) => sdk((ops) => ops.raw.tools.connections_pin_default({ path: { connection_id: connectionId } })));

export const useSendPolicy = () =>
  useTeamQuery({ queryKey: ['send-policy'], queryFn: () => sdk((ops) => ops.raw.tools.send_policy_get_send_policy()) });
export function useSaveSendPolicy() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Args<'send_policy_save_send_policy'>['body']) => sdk((ops) => ops.raw.tools.send_policy_save_send_policy({ body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['send-policy'] }),
  });
}

const mocksKey = (moduleId: string, opId: string) => ['mocks', moduleId, opId] as const;
export const useMockAnswers = (moduleId: string, opId: string) =>
  useTeamQuery({
    queryKey: mocksKey(moduleId, opId),
    queryFn: () => sdk((ops) => ops.raw.tools.tool_modules_list_mocks({ path: { module_id: moduleId, op_id: opId } })),
    enabled: Boolean(moduleId && opId),
  });
function useMockMutation<I, O>(moduleId: string, opId: string, fn: (i: I) => Promise<O>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: mocksKey(moduleId, opId) }) });
}
export const useAddMockAnswer = (moduleId: string, opId: string) =>
  useMockMutation(moduleId, opId, (body: Args<'tool_modules_add_mock'>['body']) =>
    sdk((ops) => ops.raw.tools.tool_modules_add_mock({ path: { module_id: moduleId, op_id: opId }, body })),
  );
export const useChangeMockAnswer = (moduleId: string, opId: string) =>
  useMockMutation(moduleId, opId, (a: { mockId: string; body: Args<'tool_modules_change_mock'>['body'] }) =>
    sdk((ops) => ops.raw.tools.tool_modules_change_mock({ path: { module_id: moduleId, op_id: opId, mock_id: a.mockId }, body: a.body })),
  );
export const useDeleteMockAnswer = (moduleId: string, opId: string) =>
  useMockMutation(moduleId, opId, (mockId: string) =>
    sdk((ops) => ops.raw.tools.tool_modules_delete_mock({ path: { module_id: moduleId, op_id: opId, mock_id: mockId } })),
  );
