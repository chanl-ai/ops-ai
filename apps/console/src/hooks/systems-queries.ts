'use client';

/**
 * The Apps screens' reads and writes, on the generated SDK through `sdk()` (lib/api/ops-sdk.ts): the app cards, an
 * app's page and its accounts, an account's keys, binding a module to an account, the team's sending policy and an
 * operation's mock answers. Types come from the SDK's operations, so a route change shows here as a type error, not
 * as a broken screen. An account is addressed by its app's id (`plugin:<id>`, or a custom app's id) and its own.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { sdk } from '@/lib/api/ops-sdk';
import type { AccountRef } from '@/lib/types/connections';
import type { OpsAI } from '@chanl-ai/ops-ai';

import { useTeamQuery } from './team-query';

type Tools = OpsAI['raw']['tools'];
type Args<K extends keyof Tools> = NonNullable<Parameters<Tools[K]>[0]>;
type Data<K extends keyof Tools> = Awaited<ReturnType<Tools[K]>>;

const path = (a: AccountRef) => ({ app_id: a.appId, account_id: a.accountId });

export type SystemCard = Data<'apps_list_apps'>[number];
/** An app's state on its card, worded the same on the catalog and the app page; GET /v1/apps decides it. */
export type AppState = SystemCard['appState'];
export type AccountDetail = Data<'apps_get_account'>;
export type SendPolicy = Data<'send_policy_get_send_policy'>;
export type TeamAppBody = Args<'apps_set_team_app'>['body'];
export type AccountBody = Args<'apps_add_account'>['body'];
export type MockAnswer = Data<'tool_modules_list_mocks'>['data'][number];

const SYSTEMS = ['systems'] as const;
const ACCOUNTS = ['accounts'] as const;
const APPS = ['apps'] as const;

export const useSystems = () => useTeamQuery({ queryKey: SYSTEMS, queryFn: () => sdk((ops) => ops.raw.tools.apps_list_apps()) });

function useSystemsMutation<I, O>(fn: (i: I) => Promise<O>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () =>
      Promise.all([qc.invalidateQueries({ queryKey: SYSTEMS }), qc.invalidateQueries({ queryKey: ACCOUNTS }), qc.invalidateQueries({ queryKey: APPS })]),
  });
}

export type ConnectionKinds = Data<'apps_connection_kinds'>;

export type AppPage = Data<'apps_get_app'>;
/** One app's page, joined by tools-service: card, accounts, your own sign-in, tools, skills and latest runs. */
export const useApp = (appId: string) =>
  useTeamQuery({ queryKey: [...APPS, appId], queryFn: () => sdk((ops) => ops.raw.tools.apps_get_app({ path: { app_id: appId } })) });
/** The app a chat card names, for its mark and where its records open: a side read, so a card the person may not see
 * the app of still draws, with the app's id for a name. */
export const useCardAppPage = (appId?: string) =>
  useTeamQuery({
    queryKey: [...APPS, appId ?? ''],
    queryFn: () => sdk((ops) => ops.raw.tools.apps_get_app({ path: { app_id: appId ?? '' } })),
    enabled: !!appId,
    staleTime: 5 * 60_000,
    retry: false,
    meta: { side: true },
  });
/** Disconnect: ends the caller's own sign-in on an account (DELETE /v1/me/accounts/{id}); the team's stays. */
export const useSignOutMine = () =>
  useSystemsMutation((accountId: string) => sdk((ops) => ops.raw.tools.apps_disconnect({ path: { account_id: accountId } })));

export const useConnectionKinds = () =>
  useTeamQuery({ queryKey: ['connection-kinds'], queryFn: () => sdk((ops) => ops.raw.tools.apps_connection_kinds()), staleTime: 5 * 60_000 });
export const useAccountDetail = (a: AccountRef | null) =>
  useTeamQuery({
    queryKey: [...ACCOUNTS, a?.appId, a?.accountId],
    queryFn: () => sdk((ops) => ops.raw.tools.apps_get_account({ path: path(a ?? { appId: '', accountId: '' }) })),
    enabled: Boolean(a),
  });

/**
 * The team's apps a module may sign in through, for the app picker: each card's default account, by the id a module
 * is bound to.
 */
export const useConnectionOptions = (enabled = true) =>
  useTeamQuery({
    queryKey: [...SYSTEMS, 'options'],
    queryFn: async () =>
      (await sdk((ops) => ops.raw.tools.apps_list_apps())).flatMap((c) => (c.connectionId ? [{ id: c.connectionId, name: c.name, status: c.status ?? 'draft' }] : [])),
    enabled,
  });

/** A custom app with its first account (POST /v1/apps); the answer is that account, whose `appId` names the app. */
export const useAddApp = () => useSystemsMutation((body: Args<'apps_add_app'>['body']) => sdk((ops) => ops.raw.tools.apps_add_app({ body })));
/** Another account of one of the team's apps: a sandbox, which test runs use, or another named account. */
export const useAddAccount = () =>
  useSystemsMutation((a: { appId: string; body: AccountBody }) => sdk((ops) => ops.raw.tools.apps_add_account({ path: { app_id: a.appId }, body: a.body })));
/** Changes an account: its keys and settings, who signs in, its name. `revision` is the account's as read. */
export const useChangeAccount = () =>
  useSystemsMutation((a: AccountRef & { body: Args<'apps_change_account'>['body'] }) =>
    sdk((ops) => ops.raw.tools.apps_change_account({ path: path(a), body: a.body })),
  );
export const useDeleteAccount = () => useSystemsMutation((a: AccountRef) => sdk((ops) => ops.raw.tools.apps_delete_account({ path: path(a) })));
/** Adds tools from an app's catalog to the team (POST /v1/apps/{id}/tools); agents may then pick them. */
export const useAddTools = () =>
  useSystemsMutation((a: { appId: string; tools: string[] }) => sdk((ops) => ops.raw.tools.apps_add_tools({ path: { app_id: a.appId }, body: { tools: a.tools } })));
/** Removes a tool from the team (DELETE /v1/apps/{id}/tools/{tool}); agents are no longer offered it. */
export const useRemoveTool = () =>
  useSystemsMutation((a: { appId: string; tool: string }) => sdk((ops) => ops.raw.tools.apps_remove_tool({ path: { app_id: a.appId, tool: a.tool } })));
/** Deletes the app from the team with its accounts and their secrets; refused (409 app_in_use) while a tool uses it. */
export const useDeleteApp = () => useSystemsMutation((appId: string) => sdk((ops) => ops.raw.tools.apps_delete_app({ path: { app_id: appId } })));
/** Moves every account of a custom app to another sign-in kind; the answer names the accounts to set up again. */
export const useChangeAppKind = () =>
  useSystemsMutation((a: { appId: string; kind: string }) =>
    sdk((ops) => ops.raw.tools.apps_change_app_kind({ path: { app_id: a.appId }, body: { kind: a.kind } })),
  );
/** Tests an account with the team's sign-in or the person's own; the answer is the account with its health. */
export const useTestAccount = () =>
  useSystemsMutation((a: AccountRef & { account?: 'team' | 'self' }) =>
    sdk((ops) => ops.raw.tools.apps_test_account({ path: path(a), body: { account: a.account ?? 'team' } })),
  );
/** Ends the team account's sign-in on an account (POST …/sign-out); it stays, and signs in again with Reconnect. */
export const useSignOutTeam = () => useSystemsMutation((a: AccountRef) => sdk((ops) => ops.raw.tools.apps_sign_out({ path: path(a) })));
export const useStartSignIn = () =>
  useMutation({
    mutationFn: (a: AccountRef & { account: 'team' | 'self' }) =>
      sdk((ops) => ops.raw.tools.apps_start_sign_in({ path: path(a), body: { account: a.account } })),
  });
export const useBindModule = () =>
  useSystemsMutation((a: { moduleId: string; connectionId: string | null }) =>
    sdk((ops) => ops.raw.tools.tool_modules_set_connection({ path: { module_id: a.moduleId }, body: { connectionId: a.connectionId } })),
  );
/**
 * The agents and workflows using an app's tools in the team (GET /v1/apps/{id}/used-by), read when Turn off asks;
 * admins only. A 503 tool_users_unavailable means the service could not tell, which is an error, never "nothing".
 */
export const useAppUsers = (appId: string | null) =>
  useTeamQuery({ queryKey: [...SYSTEMS, 'users', appId], queryFn: () => sdk((ops) => ops.raw.tools.apps_app_users({ path: { app_id: appId ?? '' } })), enabled: !!appId, retry: false });
/**
 * One OAuth client an app signs in with (GET /v1/app-credentials, team admins only): Ops AI's own app or the team's,
 * its permissions, how many accounts signed in through it, and its state from the last Test with my account.
 */
export type AppCredential = Data<'apps_list_app_credentials'>[number];
/** `app` keeps one app's credentials (a picker's), filtered by the API. */
export const useAppCredentials = (app?: string) =>
  useTeamQuery({
    queryKey: [...SYSTEMS, 'app-credentials', app ?? null],
    queryFn: () => sdk((ops) => ops.raw.tools.apps_list_app_credentials(app ? { query: { app } } : undefined)),
  });
/** One app credential's page (GET /v1/app-credentials/{id}): its row and the accounts signing in with it, joined. */
export type AppCredentialDetail = Data<'apps_get_app_credential'>;
export const useAppCredential = (id: string) =>
  useTeamQuery({ queryKey: [...SYSTEMS, 'app-credentials', 'one', id], enabled: Boolean(id), queryFn: () => sdk((ops) => ops.raw.tools.apps_get_app_credential({ path: { credential_id: id } })) });
/** The team's own client for an app (POST /v1/app-credentials), made with no account; answers its page. */
export const useCreateAppCredential = () =>
  useSystemsMutation((body: Args<'apps_create_app_credential'>['body']) => sdk((ops) => ops.raw.tools.apps_create_app_credential({ body })));
/** Replaces the client secret of the team's own app credential (PUT /v1/app-credentials/{id}/secret); sealed on save. */
export type AppCredentialChange = Args<'apps_change_app_credential'>['body'];
export const useChangeAppCredential = () =>
  useSystemsMutation((a: { id: string; body: AppCredentialChange }) => sdk((ops) => ops.raw.tools.apps_change_app_credential({ path: { credential_id: a.id }, body: a.body })));

/** Deletes the team's own app credential; `move` moves its accounts first, to `moveTo` or, with none, Ops AI's app. */
export const useDeleteAppCredential = () =>
  useSystemsMutation((a: { id: string; move?: boolean; moveTo?: string | null }) =>
    sdk((ops) =>
      ops.raw.tools.apps_delete_app_credential({ path: { credential_id: a.id }, query: { move: Boolean(a.move), ...(a.moveTo ? { moveTo: a.moveTo } : {}) } }),
    ),
  );

export const useSetCredentialSecret = () =>
  useSystemsMutation((a: Args<'apps_set_app_credential_secret'>) => sdk((ops) => ops.raw.tools.apps_set_app_credential_secret(a)));
/**
 * Gives the team's assistant an app's read tools (POST /v1/team-assistant/app-tools, agents-service), the Turn on
 * window's choice: which tools, and whether that was published at once, waits on a review or on someone's draft.
 */
export const useGiveAssistantAppTools = () =>
  useSystemsMutation((moduleIds: string[]) => sdk((ops) => ops.raw.agents.agents_give_assistant_app_tools({ body: { moduleIds } })));
/** Turns a plugin's app on or off for the team (PUT /v1/apps/plugin:{id}/team); answers the app's card. */
export const useSetTeamApp = () =>
  useSystemsMutation((a: { appId: string; body: TeamAppBody }) => sdk((ops) => ops.raw.tools.apps_set_team_app({ path: { app_id: a.appId }, body: a.body })));
/** Makes one of the app's accounts the caller's default: their calls that name no account use it. */
export const usePinDefault = () => useSystemsMutation((a: AccountRef) => sdk((ops) => ops.raw.tools.apps_pin_default({ path: path(a) })));
/** Makes an account the one the team's calls use when they name none (PUT …/team-default); team admins only. */
export const useMakeTeamDefault = () =>
  useSystemsMutation((a: AccountRef) => sdk((ops) => ops.raw.tools.apps_make_team_default({ path: path(a) })));

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
