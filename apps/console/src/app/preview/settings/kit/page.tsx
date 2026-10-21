'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound, Webhook } from 'lucide-react';

import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { ChoiceCards, ChoiceChecks } from '@/components/shared/setting/choice-cards';
import { CopyField, CopyId } from '@/components/shared/setting/copy-field';
import { DangerCard } from '@/components/shared/setting/danger-card';
import { EntityRow } from '@/components/shared/setting/entity-row';
import { GatedCard, ImageSettingCard } from '@/components/shared/setting/extra-cards';
import { InheritSwitch, SourceBadge } from '@/components/shared/setting/inherit-switch';
import { KeyValueEditor, type KeyValue } from '@/components/shared/setting/key-value-editor';
import { MiddleTruncate } from '@/components/shared/setting/middle-truncate';
import { Note } from '@/components/shared/setting/note';
import { Combobox, MultiSelect } from '@/components/shared/setting/pickers';
import { PrefixedInput } from '@/components/shared/setting/prefixed-input';
import { RecordTable } from '@/components/shared/setting/record-table';
import { ScopeSelect, type ScopeValue } from '@/components/shared/setting/scope-select';
import { ScrollTabsList } from '@/components/shared/setting/scroll-tabs';
import { SecretField } from '@/components/shared/setting/secret-field';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { SettingRow, SwitchRow } from '@/components/shared/setting/setting-row';
import { SplitView } from '@/components/shared/setting/split-view';
import { StatusDot } from '@/components/shared/setting/status-dot';
import { UsageBar } from '@/components/shared/setting/usage-bar';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';

import { API_KEYS, type SampleKey } from '../_sample/data';
import { mockSave } from '../_sample/save';

const MODES = [{ value: 'a', title: 'Publish at once', description: 'Nobody reviews.' }, { value: 'b', title: 'Always a review', description: 'A different person decides.' }];
const OPTIONS = [{ value: 'ops', label: 'Operations', hint: '14 members' }, { value: 'fraud', label: 'Fraud', hint: '6 members' }, { value: 'lending', label: 'Lending', hint: '9 members' }];
const COLS: ColumnDef<SampleKey>[] = [{ accessorKey: 'name', header: 'Key' }, { accessorKey: 'team', header: 'Team' }];
const TABS = ['Overview', 'Settings', 'Deployments', 'Versions', 'Test chat', 'Runs and history', 'Knowledge and tools', 'Permissions and access'].map((t) => ({ value: t, label: t }));

function Piece({ id, name, where, children }: { id: string; name: string; where: string; children: React.ReactNode }) {
  return (
    <section id={id} className="flex scroll-mt-20 flex-col gap-3" data-testid={`kit-${id}`}>
      <div>
        <h2 className="text-sm font-semibold">{name}</h2>
        <p className="text-xs text-muted-foreground">Used on {where}</p>
      </div>
      {children}
    </section>
  );
}

/** Every field and card the settings pages are built from, one of each, so a change to one is seen in one place. */
export default function KitPage() {
  const [v, setV] = React.useState('a');
  const [checks, setChecks] = React.useState<string[]>(['a']);
  const [one, setOne] = React.useState<string | null>('ops');
  const [many, setMany] = React.useState<string[]>(['ops']);
  const [kv, setKv] = React.useState<KeyValue[]>([{ key: 'X-Region', value: 'ca' }]);
  const [scope, setScope] = React.useState<Record<string, ScopeValue>>({ dev: 'default', staging: 'on', prod: 'default' });
  const [sw, setSw] = React.useState(true);
  const [inherit, setInherit] = React.useState(true);
  const [slug, setSlug] = React.useState('harborpine');
  return (
    <PreviewPageLayout title="Field kit" description="The cards and fields every settings page is built from" history={false}>
      <Piece id="setting-card" name="SettingCard" where="every page. One setting, its control, a footer with the constraint and a Save; locked, the footer names the role.">
        <SettingCard title="Display name" description="Shown on everything this owns." help="Please use 32 characters at maximum." onSave={() => mockSave('Display name')}>
          <Input defaultValue="Branch advisor" aria-label="Display name" className="w-full sm:w-1/2 bg-card" />
        </SettingCard>
        <SettingCard title="Display name (locked)" description="The same card for a person without the role." help="Please use 32 characters at maximum." locked requiredRole="Security admin" onSave={() => undefined}>
          <Input defaultValue="Branch advisor" aria-label="Display name locked" className="w-full sm:w-1/2 bg-card" />
        </SettingCard>
      </Piece>
      <Piece id="setting-row" name="SettingRow and SwitchRow" where="lists of switches (sign-in, notifications). Label, one-line effect, default, role, and a lock with the role name.">
        <div className="divide-y rounded-lg border bg-card px-4">
          <SwitchRow id="kit-sw" label="Require two-step verification" effect="People without an authenticator are sent to set one up." defaultLabel="On" role="Security admin" checked={sw} onCheckedChange={setSw} />
          <SwitchRow id="kit-sw-lock" label="Allow self-signup" effect="A new person lands in the default team." defaultLabel="Off" role="Security admin" canChange={false} checked={false} onCheckedChange={() => undefined} />
          <SettingRow id="kit-row" label="Session length" effect="How long before a person signs in again." defaultLabel="12 hours" role="Security admin">
            <div className="w-36">
              <Combobox options={[{ value: '12', label: '12 hours' }, { value: '24', label: '24 hours' }]} value="12" onChange={() => undefined} noun="lengths" />
            </div>
          </SettingRow>
        </div>
      </Piece>
      <Piece id="choice-cards" name="ChoiceCards" where="policy modes (Policies, Storage retention). Radio, or checkboxes for several.">
        <ChoiceCards name="kit-radio" label="Mode" choices={MODES} value={v} onChange={setV} />
        <ChoiceChecks name="kit-check" label="Channels" choices={MODES} value={checks} onChange={setChecks} />
      </Piece>
      <Piece id="copy-field" name="CopyField, CopyId and MiddleTruncate" where="ids, URLs and embed snippets; the id column of every records table.">
        <CopyField value="https://api.harborpine.example/ops/hooks/sources/src_9c2e41" label="URL" />
        <p className="text-sm">
          Id in a table cell: <CopyId value="ws_5e1f09a7c3b24d68" /> · truncated alone: <MiddleTruncate text="ws_5e1f09a7c3b24d68" />
        </p>
      </Piece>
      <Piece id="secret-field" name="SecretField" where="secrets, signing secrets, model keys. Masked, shown once after a rotation, with last used.">
        <SecretField name="STATEMENTS_KEY" hint="4f2a" lastUsedAt={new Date(Date.now() - 840_000).toISOString()} rotatedAt={new Date(Date.now() - 86_400_000 * 20).toISOString()} onRotate={async () => 'sk_live_6d0b91c4a73e58f2'} />
      </Piece>
      <Piece id="status-dot" name="StatusDot with a relative-time hover card" where="webhooks, providers, sync health. Hover for when it was last checked.">
        <div className="flex flex-wrap gap-6">
          <StatusDot status="ok" at={new Date(Date.now() - 120_000).toISOString()} />
          <StatusDot status="warn" at={new Date(Date.now() - 3_600_000).toISOString()} detail="2 of the last 20 deliveries failed." />
          <StatusDot status="error" at={new Date(Date.now() - 86_400_000).toISOString()} />
          <StatusDot status="idle" />
        </div>
      </Piece>
      <Piece id="entity-row" name="EntityRow" where="members, keys, hosts, devices. Avatar or icon, name, meta, trailing content and a dots menu.">
        <div className="flex flex-col gap-2">
          <EntityRow name="Maya Okafor" avatar meta="Approver · Operations" actions={[{ label: 'Change role', onClick: () => undefined }, { label: 'Remove', onClick: () => undefined, destructive: true }]} />
          <EntityRow name="Core banking runs" icon={<KeyRound className="size-4" />} meta="opk_live_8f3a… · runs:write" actions={[{ label: 'Revoke', onClick: () => undefined, destructive: true }]} />
          <EntityRow name="Case system" icon={<Webhook className="size-4" />} meta="2 events" trailing={<StatusDot status="ok" />} />
        </div>
      </Piece>
      <Piece id="key-value-editor" name="KeyValueEditor" where="webhook headers, tool headers, variables.">
        <KeyValueEditor label="Headers" value={kv} onChange={setKv} />
      </Piece>
      <Piece id="usage-bar" name="UsageBar" where="model keys, agent limits, team usage. Warns at 80% and errors at the limit.">
        <div className="flex max-w-lg flex-col gap-4">
          <UsageBar label="Monthly budget" used={2100} limit={5000} format={(n) => `$${n}`} />
          <UsageBar label="Monthly budget" used={4120} limit={5000} format={(n) => `$${n}`} />
          <UsageBar label="Requests a minute" used={310} limit={300} />
        </div>
      </Piece>
      <Piece id="note" name="Note" where="information, warnings and the sample-data banner.">
        <Note title="Information">Approvals can be decided from Email and Slack as well.</Note>
        <Note tone="warning" title="Warning">Rotating the key breaks receivers until they take the new one.</Note>
        <Note tone="sample" title="Sample data, changes aren’t saved">No service stores this page yet.</Note>
      </Piece>
      <Piece id="danger" name="DangerCard and DestructiveDialog" where="the foot of Workspace, Team and every object's Settings tab. Type the name to confirm.">
        <DangerCard title="Delete team" description="Deletes the team and hands its work to the workspace owner." precondition="Ensure nothing in the team is published." action="Delete team" confirmName="Operations" onConfirm={() => mockSave('Delete')} />
      </Piece>
      <Piece id="pickers" name="Combobox and MultiSelect" where="teams, agents, model aliases, scopes. Search, pick, remove a chip.">
        <div className="grid max-w-xl gap-3 sm:grid-cols-2">
          <Combobox options={OPTIONS} value={one} onChange={setOne} noun="teams" />
          <MultiSelect options={OPTIONS} value={many} onChange={setMany} noun="teams" />
        </div>
      </Piece>
      <Piece id="prefixed-input" name="Prefixed input" where="workspace address, SSO metadata, egress hosts.">
        <div className="w-full sm:w-1/2">
          <PrefixedInput prefix="ops.example.com/" value={slug} onChange={(e) => setSlug(e.target.value)} aria-label="Address" />
        </div>
      </Piece>
      <Piece id="scope-select" name="Per-scope select" where="a value per environment or team, side by side, with an inline Note.">
        <ScopeSelect scopes={[{ id: 'dev', label: 'Development' }, { id: 'staging', label: 'Staging' }, { id: 'prod', label: 'Production' }]} value={scope} onChange={setScope} defaultIs="on" />
      </Piece>
      <Piece id="inherit" name="InheritSwitch and SourceBadge" where="workspace settings teams may override; every value says where it comes from.">
        <div className="flex flex-wrap items-center gap-4">
          <InheritSwitch checked={inherit} onChange={setInherit} id="kit-inherit" />
          <SourceBadge level="Workspace" />
          <SourceBadge level="Team" />
          <SourceBadge level="Agent" />
        </div>
      </Piece>
      <Piece id="image-gated" name="ImageSettingCard and GatedCard" where="Workspace › General. A picture on the right; a feature that needs a plan or role, with its price and action.">
        <ImageSettingCard title="Logo" description="Shown beside the name." name="Harbor & Pine Bank" onSave={() => undefined} />
        <GatedCard title="Audit export" description="Send the audit log to the archive." needs="the Enterprise plan" price="From $400 a month" action="Talk to us" onAction={() => undefined} />
      </Piece>
      <Piece id="layout" name="Layout rules" where="every page. Fields are lighter than the page, splits resize, tab labels never spill, tables select and show ids.">
        <div className="flex flex-col gap-4">
          <div className="grid gap-3 rounded-lg bg-background p-4 sm:grid-cols-3">
            <Input aria-label="Sample field" defaultValue="Lighter than the page" className="bg-card" />
            <Textarea aria-label="Sample textarea" defaultValue="So is this" className="bg-card" />
            <Select defaultValue="a">
              <SelectTrigger aria-label="Sample select" className="w-full bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="a">And this</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <SplitView id="kit-split" left={<p className="text-sm">Left: drag the handle. The split is remembered.</p>} right={<p className="text-sm">Right: both sides keep a minimum width.</p>} />
          <div className="w-full sm:w-1/2">
            <Tabs defaultValue="Overview" className="gap-2">
              <ScrollTabsList tabs={TABS} />
            </Tabs>
            <p className="mt-1 text-xs text-muted-foreground">Eight tabs in 24rem: the list scrolls sideways.</p>
          </div>
          <RecordTable columns={COLS} data={API_KEYS} nameOf={(k) => k.name} searchPlaceholder="Search keys…" />
        </div>
      </Piece>
    </PreviewPageLayout>
  );
}
