'use client';

import * as React from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { Controller, useForm } from 'react-hook-form';
import { ChevronDown, Lock } from 'lucide-react';
import { toast } from 'sonner';
import { z } from 'zod';

import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { EntityPicker } from '@/components/shared/entity-picker';
import { QueryError } from '@/components/shared/query-states';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { appOptions, useOptionLabels } from '@/hooks/options-queries';
import { useCan, useRoles } from '@/hooks/me-queries';
import { TOOL_KEY, usePolicyEditor, useSetWorkspacePolicy, useWorkspacePolicies } from '@/hooks/policy-queries';
import { usePoliciesAreSample } from '@/hooks/use-preview';
import { useTeam } from '@/hooks/use-team';
import { ApiError } from '@/lib/api/contract';

// The answer that asks someone other than the asker (an answer, not a role name).
const BY_REVIEWER = 'reviewer';
const SWITCH = 'Ask before an agent changes anything in an app';
const OWN_REQUESTS = 'People can approve their own requests';
const TEST_ACCOUNTS = 'Test accounts never ask';
const TEST_RUNS = 'Test runs on live accounts ask first';
const MAKERS = 'Writes an app or template marks “ask first” wait for approval';
const NOT_THESE_ROLES = new Set(['viewer', 'chat_user', 'owner', 'builder']);

const teamSchema = z
  .object({ ask: z.boolean(), answer: z.enum(['person', 'reviewer']), reviewerRole: z.string().nullable(), requesterMayDecide: z.boolean(), testAccountsNeverAsk: z.boolean(), testRunsAsk: z.boolean(), makersAsk: z.boolean() })
  .refine((v) => !v.ask || v.answer !== BY_REVIEWER || !!v.reviewerRole, { message: 'Choose the role that reviews.', path: ['reviewerRole'] });
type TeamForm = z.infer<typeof teamSchema>;

type Entry = { answer: 'none' | 'person' | 'reviewer'; reviewerRole?: string | null };
const ANSWERS: { value: string; label: string }[] = [
  { value: 'team', label: 'Use the team setting' },
  { value: 'none', label: 'Don’t ask' },
  { value: 'person', label: 'Ask the person' },
  { value: 'reviewer', label: 'Ask a reviewer' },
];

const ofTeam = (value: unknown, teamId: string) => {
  // `*` is the workspace's own part (a new workspace's makersAsk); the team's saved part wins over it.
  const map = value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
  const part = (k: string) => (map[k] && typeof map[k] === 'object' ? (map[k] as Record<string, unknown>) : {});
  return { ...part('*'), ...part(teamId) };
};

/** Govern › Approvals: one switch for whether an agent asks before it changes an app, and who answers. */
export default function ApprovalsPage() {
  const policies = useWorkspacePolicies();
  const editor = usePolicyEditor();
  const sample = usePoliciesAreSample();
  const { team } = useTeam();
  const teamId = team?.id ?? '';
  const set = useSetWorkspacePolicy();
  const roles = useRoles();
  const changes = policies.data?.find((p) => p.key === 'appChanges');
  const byApp = policies.data?.find((p) => p.key === 'appChangesByApp');
  const saved = ofTeam(changes?.value, teamId);
  const mayDecide = policies.data?.find((p) => p.key === 'requesterMayDecide');
  const savedAll = React.useMemo(() => ofTeam(byApp?.value, teamId) as Record<string, Entry>, [byApp?.value, teamId]);
  // A key starting `tool:` is one tool's answer, set on that tool's own page; it is kept as it is when apps are saved.
  const savedByApp = React.useMemo(() => Object.fromEntries(Object.entries(savedAll).filter(([k]) => !k.startsWith(TOOL_KEY))), [savedAll]);
  const savedTools = React.useMemo(() => Object.fromEntries(Object.entries(savedAll).filter(([k]) => k.startsWith(TOOL_KEY))), [savedAll]);
  // Both policies are changed under settings.manage; the cell is held in the Security team or the acting team.
  const locked = useCan('settings', 'manage') !== true || sample;
  const roleList = (roles.data ?? []).filter((r: { id: string }) => !NOT_THESE_ROLES.has(r.id));

  const form = useForm<TeamForm>({
    resolver: zodResolver(teamSchema),
    values: {
      ask: saved.ask === true,
      answer: saved.answer === BY_REVIEWER ? BY_REVIEWER : 'person',
      reviewerRole: (saved.reviewerRole as string | null) ?? null,
      requesterMayDecide: mayDecide?.value === true,
      testAccountsNeverAsk: saved.testAccountsNeverAsk !== false,
      testRunsAsk: saved.testRunsAsk !== false,
      // Unset means a maker's ask-first holds; a new workspace stores false for the whole workspace.
      makersAsk: saved.makersAsk !== false,
    },
  });
  const ask = form.watch('ask');
  const answer = form.watch('answer');
  const [overrides, setOverrides] = React.useState<Record<string, Entry>>(savedByApp);
  React.useEffect(() => {
    setOverrides(savedByApp);
  }, [savedByApp]);
  const appIds = Object.keys(overrides);
  const labelRows = useOptionLabels(appOptions, appIds).data?.data ?? [];
  const nameOf = (id: string) => labelRows.find((r) => r.id === id)?.label ?? id;

  const saveTeam = form.handleSubmit(async (v) => {
    try {
      await set.mutateAsync({ key: 'appChanges', teamId, value: { ask: v.ask, answer: v.answer, reviewerRole: v.answer === BY_REVIEWER ? v.reviewerRole : null, testAccountsNeverAsk: saved.testAccountsNeverAsk !== false, testRunsAsk: saved.testRunsAsk !== false, ...(typeof saved.makersAsk === 'boolean' ? { makersAsk: saved.makersAsk } : {}) } });
      if (v.requesterMayDecide !== (mayDecide?.value === true)) await set.mutateAsync({ key: 'requesterMayDecide', value: v.requesterMayDecide });
      toast.success(`Saved: ${SWITCH}`, { description: 'New requests follow it. Open ones keep the rule they were made under.' });
    } catch (e) {
      toast.error('Couldn’t save the approval setting', { description: (e as Error).message });
    }
  });
  // Saves the checkbox alone, on top of what the team saved, so a half-edited switch above is not stored with it.
  const saveTestAccounts = async () => {
    try {
      const value = { ask: saved.ask === true, answer: saved.answer === BY_REVIEWER ? BY_REVIEWER : 'person', reviewerRole: (saved.reviewerRole as string | null) ?? null, testAccountsNeverAsk: form.getValues('testAccountsNeverAsk'), testRunsAsk: saved.testRunsAsk !== false, ...(typeof saved.makersAsk === 'boolean' ? { makersAsk: saved.makersAsk } : {}) };
      await set.mutateAsync({ key: 'appChanges', teamId, value });
      toast.success(`Saved: ${TEST_ACCOUNTS}`);
    } catch (e) {
      toast.error('Couldn’t save the test account setting', { description: (e as Error).message });
    }
  };
  const saveTestRuns = async () => {
    try {
      const value = { ask: saved.ask === true, answer: saved.answer === BY_REVIEWER ? BY_REVIEWER : 'person', reviewerRole: (saved.reviewerRole as string | null) ?? null, testAccountsNeverAsk: saved.testAccountsNeverAsk !== false, testRunsAsk: form.getValues('testRunsAsk'), ...(typeof saved.makersAsk === 'boolean' ? { makersAsk: saved.makersAsk } : {}) };
      await set.mutateAsync({ key: 'appChanges', teamId, value });
      toast.success(`Saved: ${TEST_RUNS}`);
    } catch (e) {
      toast.error('Couldn’t save the test run setting', { description: (e as Error).message });
    }
  };
  // Saves this switch alone into the team's part, on top of what the team saved; the team's part wins over the workspace's.
  const saveMakers = async () => {
    try {
      const value = { ask: saved.ask === true, answer: saved.answer === BY_REVIEWER ? BY_REVIEWER : 'person', reviewerRole: (saved.reviewerRole as string | null) ?? null, testAccountsNeverAsk: saved.testAccountsNeverAsk !== false, testRunsAsk: saved.testRunsAsk !== false, makersAsk: form.getValues('makersAsk') };
      await set.mutateAsync({ key: 'appChanges', teamId, value });
      toast.success(`Saved: ${MAKERS}`, { description: 'New requests follow it. Open ones keep the rule they were made under.' });
    } catch (e) {
      toast.error(`Couldn’t save: ${MAKERS}`, { description: (e as Error).message });
    }
  };
  const saveApps = async () => {
    try {
      await set.mutateAsync({ key: 'appChangesByApp', teamId, value: { ...savedTools, ...overrides } });
      toast.success('Saved the app overrides');
    } catch (e) {
      toast.error('Couldn’t save the app overrides', { description: (e as Error).message });
    }
  };

  return (
    <SettingsPageLayout section="Approvals" description="Whether an agent asks before it changes something in an app. Off until you turn it on." sample={sample}>
      {policies.isPending || editor.isPending ? (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-44 w-full" />
        </div>
      ) : policies.error instanceof ApiError && policies.error.status === 403 ? (
        <EmptyState icon={Lock} title="You can’t see approvals" description={policies.error.message} testId="approvals-refused" />
      ) : policies.isError ? (
        <QueryError what="the approval settings" error={policies.error} onRetry={() => policies.refetch()} retrying={policies.isFetching} />
      ) : (
        <>
          <SettingCard
            id="approvals-team"
            title={SWITCH}
            description="Off: agents change apps without asking. On: the person in the chat confirms, or a reviewer approves. Reading never asks."
            help="Default: off · Changed by a team admin"
            locked={locked}
            requiredRole="admin"
            onSave={saveTeam}
            saving={set.isPending}
            dirty={Object.keys(form.formState.dirtyFields).some((k) => k !== 'testAccountsNeverAsk' && k !== 'testRunsAsk' && k !== 'makersAsk')}
          >
            <div className="flex flex-col gap-4">
              <Controller
                control={form.control}
                name="ask"
                render={({ field }) => <Switch checked={field.value} onCheckedChange={field.onChange} disabled={locked} aria-label={SWITCH} />}
              />
              {ask && (
                <>
                  <Controller
                    control={form.control}
                    name="answer"
                    render={({ field }) => (
                      <ChoiceCards
                        name="approvals-answer"
                        label="Who answers"
                        value={field.value}
                        onChange={field.onChange}
                        choices={[
                          { value: 'person', title: 'Ask the person', description: 'The person in the chat confirms. Only they can.' },
                          { value: 'reviewer', title: 'Ask a reviewer', description: 'Someone else with the role you choose approves. Nobody approves their own request.' },
                        ]}
                      />
                    )}
                  />
                  {answer === BY_REVIEWER && (
                    <Controller
                      control={form.control}
                      name="reviewerRole"
                      render={({ field, fieldState }) => (
                        <div className="flex flex-col gap-1">
                          <Select value={field.value ?? ''} onValueChange={field.onChange} disabled={locked}>
                            <SelectTrigger className="w-64 bg-card" aria-label="Reviewer role">
                              <SelectValue placeholder="Choose a role" />
                            </SelectTrigger>
                            <SelectContent>
                              {roleList.map((r: { id: string; name: string }) => (
                                <SelectItem key={r.id} value={r.id}>
                                  {r.name}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          {fieldState.error && <p className="text-xs text-destructive">{fieldState.error.message}</p>}
                        </div>
                      )}
                    />
                  )}
                  {answer === BY_REVIEWER && (
                    <Controller
                      control={form.control}
                      name="requesterMayDecide"
                      render={({ field }) => (
                        <label className="flex items-start gap-2 text-sm">
                          <Checkbox checked={field.value} onCheckedChange={(v) => field.onChange(v === true)} disabled={locked} aria-label={OWN_REQUESTS} className="mt-0.5" />
                          <span>
                            {OWN_REQUESTS}
                            <span className="block text-xs text-muted-foreground">Off: someone else has to approve. Applies to every team in the workspace.</span>
                          </span>
                        </label>
                      )}
                    />
                  )}
                </>
              )}
            </div>
          </SettingCard>

          <SettingCard
            id="approvals-makers"
            title={MAKERS}
            description="Some app actions and template tools are marked by their maker to ask first. Off: they run like any other write, and the switch above decides. A new workspace starts with this off."
            help="Default: off in a new workspace · Changed by a team admin"
            locked={locked}
            requiredRole="admin"
            onSave={saveMakers}
            saving={set.isPending}
            dirty={form.formState.dirtyFields.makersAsk === true}
          >
            <Controller
              control={form.control}
              name="makersAsk"
              render={({ field }) => (
                <label className="flex items-center gap-3 text-sm">
                  <Switch checked={field.value} onCheckedChange={field.onChange} disabled={locked} aria-label={MAKERS} data-testid="approvals-makers-switch" />
                  {field.value ? 'On: they wait for approval' : 'Off: they run unless the switch above asks'}
                </label>
              )}
            />
          </SettingCard>

          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" data-testid="approvals-advanced">
                Advanced <ChevronDown className="size-4" />
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-2 flex flex-col gap-4">
              <SettingCard
                id="approvals-test-accounts"
                title={TEST_ACCOUNTS}
                description="A write signed in with an app’s test account changes nothing real, so it runs without asking even while the switch above is on."
                help="Default: on · Changed by a team admin"
                locked={locked}
                requiredRole="admin"
                onSave={saveTestAccounts}
                saving={set.isPending}
                dirty={form.formState.dirtyFields.testAccountsNeverAsk === true}
              >
                <Controller
                  control={form.control}
                  name="testAccountsNeverAsk"
                  render={({ field }) => (
                    <label className="flex items-center gap-2 text-sm">
                      <Checkbox checked={field.value} onCheckedChange={(v) => field.onChange(v === true)} disabled={locked} aria-label={TEST_ACCOUNTS} />
                      {TEST_ACCOUNTS}
                    </label>
                  )}
                />
              </SettingCard>
              <SettingCard
                id="approvals-test-runs"
                title={TEST_RUNS}
                description="A test run that writes with an app’s live account pauses for a yes from the person running it, even while the switch above is off."
                help="Default: on · Changed by a team admin"
                locked={locked}
                requiredRole="admin"
                onSave={saveTestRuns}
                saving={set.isPending}
                dirty={form.formState.dirtyFields.testRunsAsk === true}
              >
                <Controller
                  control={form.control}
                  name="testRunsAsk"
                  render={({ field }) => (
                    <label className="flex items-center gap-2 text-sm">
                      <Checkbox checked={field.value} onCheckedChange={(v) => field.onChange(v === true)} disabled={locked} aria-label={TEST_RUNS} />
                      {TEST_RUNS}
                    </label>
                  )}
                />
              </SettingCard>
              <SettingCard
                id="approvals-apps"
                title="By app"
                description="An app can follow the team or choose its own answer. The app’s answer wins over the team’s. A tool can override its app on the tool’s own page."
                locked={locked}
                requiredRole="admin"
                onSave={saveApps}
                saving={set.isPending}
                dirty={JSON.stringify(overrides) !== JSON.stringify(savedByApp)}
              >
                <div className="flex flex-col gap-3">
                  <EntityPicker
                    source={appOptions}
                    value={appIds}
                    onChange={(ids) => setOverrides(Object.fromEntries(ids.map((id) => [id, overrides[id] ?? { answer: 'none' }])))}
                    addLabel="Add app"
                    searchPlaceholder="Search apps"
                    emptyText="No app matches. Apps your team connected are listed on Apps."
                    showChosen={false}
                    testId="approvals-app-picker"
                  />
                  {appIds.map((id) => (
                    <div key={id} className="flex flex-wrap items-center gap-3" data-testid={`approvals-app-${id}`}>
                      <span className="min-w-40 text-sm font-medium">{nameOf(id)}</span>
                      <Select
                        value={overrides[id]?.answer ?? 'team'}
                        onValueChange={(v) => {
                          const next = { ...overrides };
                          if (v === 'team') delete next[id];
                          else next[id] = { answer: v as Entry['answer'], reviewerRole: v === BY_REVIEWER ? (overrides[id]?.reviewerRole ?? (saved.reviewerRole as string | null)) : undefined };
                          setOverrides(next);
                        }}
                      >
                        <SelectTrigger className="w-56 bg-card" aria-label={`Answer for ${nameOf(id)}`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ANSWERS.map((a) => (
                            <SelectItem key={a.value} value={a.value}>
                              {a.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  ))}
                </div>
              </SettingCard>
            </CollapsibleContent>
          </Collapsible>
        </>
      )}
    </SettingsPageLayout>
  );
}
