'use client';

import * as React from 'react';
import Link from 'next/link';
import { Lock } from 'lucide-react';

import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { EntityPicker } from '@/components/shared/entity-picker';
import { FormFieldGroup } from '@/components/shared/form-field';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { Note } from '@/components/shared/setting/note';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { appOptions } from '@/hooks/options-queries';
import { usePolicyEditor, useSetWorkspacePolicy, useWorkspacePolicies } from '@/hooks/policy-queries';
import { useSaveSendPolicy, useSendPolicy } from '@/hooks/systems-queries';
import { usePoliciesAreSample } from '@/hooks/use-preview';
import { useTeam } from '@/hooks/use-team';
import { ApiError } from '@/lib/api/contract';
import { relativeTime } from '@/lib/format';
import type { PolicyKind, PolicyValue, WorkspacePolicy } from '@/lib/types/workspace-policies';
import { toast } from 'sonner';

// The approval policies are set on Approvals; the old keys are derived from it.
const APPROVAL_KEYS = new Set(['appChanges', 'appChangesByApp', 'toolWritesNeedApproval', 'appWritesNeedApproval', 'appsChangeWithoutAsking', 'requesterMayDecide']);
const FLOOR = [
  { value: 'none', title: 'None', description: '' },
  { value: '0.7', title: '70%', description: '' },
  { value: '0.8', title: '80%', description: '' },
  { value: '0.85', title: '85%', description: '' },
  { value: '0.95', title: '95%', description: '' },
];
const SWITCH = [
  { value: 'true', title: 'On', description: '' },
  { value: 'false', title: 'Off', description: '' },
];
const isMap = (v: PolicyValue): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const asChoice = (v: PolicyValue) => (v === null ? 'none' : isMap(v) ? '' : String(v));
// A choice policy (egressNewHosts) keeps its option's value as text, whatever it looks like.
const isChoice = (p: WorkspacePolicy) => kindOf(p) === 'choice' && Boolean(p.choices?.length);
const fromChoice = (c: string): PolicyValue => (c === 'none' ? null : c === 'true' ? true : c === 'false' ? false : Number(c));
// A row from before kinds were served is read from its value's shape.
const kindOf = (p: WorkspacePolicy): PolicyKind =>
  p.kind ?? (isMap(p.default) ? 'publish_modes' : typeof p.default === 'boolean' ? 'bool' : p.key.endsWith('Days') ? 'days' : p.key.endsWith('Hours') ? 'hours' : 'floor');
const UNITS: Partial<Record<PolicyKind, string>> = { days: 'days', hours: 'hours' };
const titleOf = (p: WorkspacePolicy) => p.title ?? p.key;
// A per-team switch: an on-off policy whose value is { team: bool }; a team that has not set it is off.
const isTeamSwitch = (p: WorkspacePolicy) => kindOf(p) === 'bool' && isMap(p.default);
const defaultLabel = (p: WorkspacePolicy) => {
  const unit = UNITS[kindOf(p)];
  if (isTeamSwitch(p)) return 'Off for every team';
  if (kindOf(p) === 'names') return 'No app listed';
  if (isChoice(p)) return p.choices?.find((c) => c.value === p.default)?.title ?? String(p.default);
  if (isMap(p.default)) return 'Review major changes';
  if (typeof p.default === 'boolean') return p.default ? 'On' : 'Off';
  if (p.default === null || Array.isArray(p.default)) return unit ? 'No limit' : 'None';
  if (typeof p.default === 'string') return p.default;
  return unit ? `${p.default} ${unit}` : `${Math.round(p.default * 100)}%`;
};

function PolicyCard({ policy, cells, sample, teamId }: { policy: WorkspacePolicy; cells: Record<string, string[]>; sample: boolean; teamId: string }) {
  const set = useSetWorkspacePolicy();
  const kind = kindOf(policy);
  const unit = UNITS[kind];
  // publishReview's value is { team: { area: mode } }; the card edits the acting team's part.
  const teamModes = React.useMemo(() => (isMap(policy.value) ? ((policy.value[teamId] as Record<string, string> | undefined) ?? {}) : {}), [policy.value, teamId]);
  const teamSwitch = isTeamSwitch(policy);
  // A per-team switch shows the acting team's own setting.
  const current = teamSwitch ? String(isMap(policy.value) && policy.value[teamId] === true) : asChoice(policy.value);
  const [draft, setDraft] = React.useState(current);
  const [modes, setModes] = React.useState<Record<string, string>>(teamModes);
  React.useEffect(() => {
    setDraft(current);
    setModes(teamModes);
  }, [current, teamModes]);
  // Whether the person may change this one comes from the server's own grid: the cell the policy names.
  const roles = cells[policy.changedBy] ?? [];
  const common = { id: `policy-${policy.key}`, title: titleOf(policy), description: policy.effect, help: `Default: ${defaultLabel(policy)}${roles.length ? ` · Changed by ${roles.join(', ')}` : ''}`, locked: !(policy.changedBy in cells) || sample, requiredRole: roles.join(' or ') || undefined };
  const per = kind === 'publish_modes';
  // A per-team list (appWritesNeedApproval): the acting team's names under its id; a team that set nothing lists none.
  const names = kind === 'names';
  const teamNames = React.useMemo(() => {
    const listed = isMap(policy.value) ? policy.value[teamId] : undefined;
    return Array.isArray(listed) ? listed.map(String) : [];
  }, [policy.value, teamId]);
  const [picked, setPicked] = React.useState<string[]>(teamNames);
  React.useEffect(() => {
    setPicked(teamNames);
  }, [teamNames]);
  const save = async () => {
    try {
      const value: PolicyValue = names ? picked : per ? modes : isChoice(policy) ? draft : unit ? (draft.trim() === '' || draft === 'none' ? null : Number(draft)) : fromChoice(draft);
      await set.mutateAsync({ key: policy.key, value, teamId });
      toast.success(`Saved ${titleOf(policy)}`, { description: 'New requests follow it. Open ones keep the rule they were made under.' });
    } catch (e) {
      toast.error('Couldn’t save the policy', { description: (e as Error).message });
    }
  };
  const dirty = names ? JSON.stringify(picked) !== JSON.stringify(teamNames) : per ? JSON.stringify(modes) !== JSON.stringify(teamModes) : draft !== current;
  // Which publishes need a review is edited in one place, Publish reviews; this card says so and links there.
  if (per)
    return (
      <SettingCard {...common}>
        <Button asChild variant="outline" size="sm" data-testid="policy-open-publish-reviews">
          <Link href="/settings/publish-reviews">Set it on Publish reviews</Link>
        </Button>
      </SettingCard>
    );
  if (names)
    return (
      <SettingCard {...common} onSave={save} saving={set.isPending} dirty={dirty}>
        <FormFieldGroup label="Apps whose writes need approval" hint="A write from a listed app waits for a person; other writes run unless their tool asks.">
        <EntityPicker
          source={appOptions}
          value={picked}
          onChange={setPicked}
          addLabel="Add app"
          searchPlaceholder="Search apps"
          emptyText="No app matches. Apps your team connected are listed on Apps."
          disabled={common.locked}
          testId={`policy-${policy.key}-apps`}
        />
        </FormFieldGroup>
      </SettingCard>
    );
  return (
    <SettingCard {...common} onSave={save} saving={set.isPending} dirty={dirty}>
      {unit ? (
        <div className="flex items-center gap-2">
          <Input type="number" min={1} value={draft === 'none' ? '' : draft} onChange={(e) => setDraft(e.target.value)} placeholder={policy.default === null ? 'e.g. 90' : undefined} aria-label={`${titleOf(policy)} in ${unit}`} className="w-40 bg-card" />
          <span className="text-sm text-muted-foreground">{unit}</span>
        </div>
      ) : isChoice(policy) ? (
        <div className="flex flex-col gap-2">
          <ChoiceCards
            name={policy.key}
            label={titleOf(policy)}
            choices={(policy.choices ?? []).map((c) => ({ value: c.value, title: c.title, description: c.description ?? '' }))}
            value={draft}
            onChange={setDraft}
          />
          {policy.note && (
            <p className="text-xs text-muted-foreground" data-testid={`policy-${policy.key}-note`}>
              {policy.note}
            </p>
          )}
        </div>
      ) : (
        <ChoiceCards name={policy.key} label={titleOf(policy)} choices={kind === 'floor' ? FLOOR : SWITCH} value={draft} onChange={setDraft} />
      )}
    </SettingCard>
  );
}

/**
 * The team's sending policy: the plain words Check before sending reads a write against. Each save is a new
 * version; a run is checked against the newest one when its write is about to go out.
 */
function SendPolicyCard({ locked }: { locked: boolean }) {
  const policy = useSendPolicy();
  const save = useSaveSendPolicy();
  const saved = policy.data?.text ?? '';
  const [text, setText] = React.useState(saved);
  React.useEffect(() => {
    setText(saved);
  }, [saved]);
  const v = policy.data;
  const submit = async () => {
    try {
      const out = await save.mutateAsync({ text: text.trim() });
      toast.success(`Saved the sending policy, version ${out.version}`, { description: 'The next write a run sends is checked against it.' });
    } catch (e) {
      toast.error('Couldn’t save the sending policy', { description: (e as Error).message });
    }
  };
  return (
    <SettingCard
      id="send-policy"
      title="Sending policy"
      description="What Check before sending reads each write against, in plain words: what a reply or a record must never say or do."
      help={v ? `Version ${v.version}, saved by ${v.savedBy} ${relativeTime(v.savedAt)}` : policy.isPending ? 'Loading…' : 'Not written yet'}
      locked={locked}
      onSave={submit}
      saving={save.isPending}
      dirty={text.trim() !== saved.trim() && Boolean(text.trim())}
    >
      {policy.isError ? (
        <QueryError what="the sending policy" error={policy.error} onRetry={() => policy.refetch()} retrying={policy.isFetching} />
      ) : (
        <Textarea
          id="send-policy-text"
          aria-label="Sending policy"
          rows={5}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Never promise a refund, or any money back, in a case or a reply."
          className="bg-card"
          disabled={locked}
        />
      )}
    </SettingCard>
  );
}

/** Govern › Policies: one card per workspace policy, read from and saved to platform-service (GET and PUT /v1/policies). */
export default function PoliciesPage() {
  const policies = useWorkspacePolicies();
  const editor = usePolicyEditor();
  const sample = usePoliciesAreSample();
  // The resolved team: its id is what the server files a per-team policy under.
  const { team } = useTeam();
  return (
    <SettingsPageLayout section="Policies" description="Who may decide what, and which publishes need a review. Every default is open." sample={sample}>
      <Note title="Every default is open">A policy you have not set behaves as its default. A change applies to new requests; open ones keep the rule they were made under.</Note>
      {policies.isPending || editor.isPending ? (
        <div className="flex flex-col gap-4" aria-busy="true">
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-44 w-full" />
          <Skeleton className="h-44 w-full" />
        </div>
      ) : policies.error instanceof ApiError && policies.error.status === 403 ? (
        // Reading policies is the security team's too; the server's own refusal says which role and who holds it.
        <EmptyState icon={Lock} title="You can’t see the policies" description={policies.error.message} testId="policies-refused" />
      ) : policies.isError ? (
        <QueryError what="the policies" error={policies.error} onRetry={() => policies.refetch()} retrying={policies.isFetching} />
      ) : (
        <div className="flex flex-col gap-4" data-testid="policy-cards">
          {/* The install's plugins are switched through the API; they have no editor on this page yet. */}
          {policies.data.filter((p) => !APPROVAL_KEYS.has(p.key)).map((p) => (
            <React.Fragment key={p.key}>
              <PolicyCard policy={p} cells={editor.data?.cells ?? {}} sample={sample} teamId={team?.id ?? ''} />
              {/* The words Check before sending reads, right after the switch that turns it on. */}
              {p.key === 'checkBeforeSend' && <SendPolicyCard locked={!(p.changedBy in (editor.data?.cells ?? {})) || sample} />}
            </React.Fragment>
          ))}
        </div>
      )}
      <p className="text-sm text-muted-foreground">
        Which publishes need a review, area by area, is set under{' '}
        <Link href="/settings/publish-reviews" className="text-primary underline-offset-4 hover:underline">
          Publish reviews
        </Link>
        ; whether agents ask before they change an app, under{' '}
        <Link href="/settings/approvals" className="text-primary underline-offset-4 hover:underline">
          Approvals
        </Link>
        ; who decides at each gate, under{' '}
        <Link href="/work/tasks/policies" className="text-primary underline-offset-4 hover:underline">
          Gate policies
        </Link>
        .
      </p>
    </SettingsPageLayout>
  );
}
