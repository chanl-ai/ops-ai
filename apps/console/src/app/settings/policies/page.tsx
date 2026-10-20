'use client';

import * as React from 'react';
import Link from 'next/link';
import { Lock } from 'lucide-react';

import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { ChoiceCards } from '@/components/shared/setting/choice-cards';
import { Note } from '@/components/shared/setting/note';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { usePolicyEditor, useSetWorkspacePolicy, useWorkspacePolicies } from '@/hooks/policy-queries';
import { usePoliciesAreSample } from '@/hooks/use-preview';
import { useTeam } from '@/hooks/use-team';
import { ApiError } from '@/lib/api/contract';
import type { PolicyKind, PolicyValue, WorkspacePolicy } from '@/lib/types/workspace-policies';
import { toast } from 'sonner';

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
const isMap = (v: PolicyValue): v is Record<string, unknown> => typeof v === 'object' && v !== null;
const asChoice = (v: PolicyValue) => (v === null ? 'none' : isMap(v) ? '' : String(v));
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
  if (isMap(p.default)) return 'Review major changes';
  if (typeof p.default === 'boolean') return p.default ? 'On' : 'Off';
  if (p.default === null) return unit ? 'No limit' : 'None';
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
  const save = async () => {
    try {
      const value: PolicyValue = per ? modes : unit ? (draft.trim() === '' || draft === 'none' ? null : Number(draft)) : fromChoice(draft);
      await set.mutateAsync({ key: policy.key, value, teamId });
      toast.success(`Saved ${titleOf(policy)}`, { description: 'New requests follow it. Open ones keep the rule they were made under.' });
    } catch (e) {
      toast.error('Couldn’t save the policy', { description: (e as Error).message });
    }
  };
  const dirty = per ? JSON.stringify(modes) !== JSON.stringify(teamModes) : draft !== current;
  // Which publishes need a review is edited in one place, Publish reviews; this card says so and links there (c-214).
  if (per)
    return (
      <SettingCard {...common}>
        <Button asChild variant="outline" size="sm" data-testid="policy-open-publish-reviews">
          <Link href="/settings/publish-reviews">Set it on Publish reviews</Link>
        </Button>
      </SettingCard>
    );
  return (
    <SettingCard {...common} onSave={save} saving={set.isPending} dirty={dirty}>
      {unit ? (
        <div className="flex items-center gap-2">
          <Input type="number" min={1} value={draft === 'none' ? '' : draft} onChange={(e) => setDraft(e.target.value)} placeholder={policy.default === null ? 'e.g. 90' : undefined} aria-label={`${titleOf(policy)} in ${unit}`} className="w-40 bg-card" />
          <span className="text-sm text-muted-foreground">{unit}</span>
        </div>
      ) : (
        <ChoiceCards name={policy.key} label={titleOf(policy)} choices={kind === 'floor' ? FLOOR : SWITCH} value={draft} onChange={setDraft} />
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
          {policies.data.map((p) => (
            <PolicyCard key={p.key} policy={p} cells={editor.data?.cells ?? {}} sample={sample} teamId={team?.id ?? ''} />
          ))}
        </div>
      )}
      <p className="text-sm text-muted-foreground">
        Which publishes need a review, area by area, is set under{' '}
        <Link href="/settings/publish-reviews" className="text-primary underline-offset-4 hover:underline">
          Publish reviews
        </Link>
        ; who decides at each gate, under{' '}
        <Link href="/reviews/policies" className="text-primary underline-offset-4 hover:underline">
          Gate policies
        </Link>
        .
      </p>
    </SettingsPageLayout>
  );
}
