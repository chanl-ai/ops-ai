'use client';

/**
 * The real-connections screens' reads and writes (c-580), on the generated SDK through `sdk()` (lib/api/ops-sdk.ts):
 * the systems grid, a connection's keys per environment, a plugin's own app per environment, binding a module to its
 * connection, the team's sending policy and an operation's mock answers. Types come from the SDK's operations, so a
 * route change shows here as a type error, not as a broken screen.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { realConnections } from '@/lib/api';
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

/** Whether the console offers the real-connections screens (the NEXT_PUBLIC_OPS_REAL_CONNECTIONS switch). */
export const useRealConnections = (): boolean => realConnections;

export const useSystems = () =>
  useTeamQuery({ queryKey: SYSTEMS, queryFn: () => sdk((ops) => ops.raw.tools.connections_list_systems()), enabled: realConnections });
export const usePlugins = () =>
  useTeamQuery({ queryKey: ['plugins'], queryFn: () => sdk((ops) => ops.raw.tools.plugins_list_plugins()), enabled: realConnections });

function useSystemsMutation<I, O>(fn: (i: I) => Promise<O>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: SYSTEMS }), qc.invalidateQueries({ queryKey: CONNECTIONS })]),
  });
}

export type ConnectionKinds = Data<'connections_kinds'>;
/** The routes' environment parameter. The console holds environments as the ids GET /v1/connection-kinds lists. */
type ApiEnvironment = NonNullable<Args<'connections_test_connection'>['body']>['environment'];
const env = (id: string) => id as ApiEnvironment;

export const useConnectionKinds = () =>
  useTeamQuery({ queryKey: ['connection-kinds'], queryFn: () => sdk((ops) => ops.raw.tools.connections_kinds()), staleTime: 5 * 60_000 });
export const useConnectionDetail = (connectionId: string | null | undefined) =>
  useTeamQuery({
    queryKey: [...CONNECTIONS, connectionId],
    queryFn: () => sdk((ops) => ops.raw.tools.connections_get_connection({ path: { connection_id: connectionId ?? '' } })),
    enabled: Boolean(connectionId),
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
export const useSetTeamPlugin = () => useSystemsMutation((a: Args<'plugins_set_team_plugin'>) => sdk((ops) => ops.raw.tools.plugins_set_team_plugin(a)));

export const useSendPolicy = () =>
  useTeamQuery({ queryKey: ['send-policy'], queryFn: () => sdk((ops) => ops.raw.tools.send_policy_get_send_policy()), enabled: realConnections });
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
    enabled: realConnections && Boolean(moduleId && opId),
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
