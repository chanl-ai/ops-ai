'use client';

import * as React from 'react';
import Link from 'next/link';

import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { DangerCard } from '@/components/shared/setting/danger-card';
import { CopyField } from '@/components/shared/setting/copy-field';
import { GatedCard, ImageSettingCard } from '@/components/shared/setting/extra-cards';
import { InheritSwitch, SourceBadge } from '@/components/shared/setting/inherit-switch';
import { Note } from '@/components/shared/setting/note';
import { Combobox } from '@/components/shared/setting/pickers';
import { PrefixedInput } from '@/components/shared/setting/prefixed-input';
import { ScopeSelect, type ScopeValue } from '@/components/shared/setting/scope-select';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useViewerRole } from '@/lib/settings-preview-store';

import { mockSave } from '../_sample/save';

const ALIASES = [
  { value: 'advisor-default', label: 'advisor-default', hint: 'gpt-5.1' },
  { value: 'policy-strict', label: 'policy-strict', hint: 'claude-sonnet-4-5' },
];

/** Workspace › General: the Vercel pattern, one setting per card, each with its own Save and a footer that states the limit. */
export default function WorkspaceGeneralPage() {
  const { can } = useViewerRole();
  const admin = can('Admin');
  const [name, setName] = React.useState('Harbor & Pine Bank');
  const [slug, setSlug] = React.useState('harborpine');
  const [alias, setAlias] = React.useState<string | null>('advisor-default');
  const [overridable, setOverridable] = React.useState(true);
  const [notify, setNotify] = React.useState<Record<string, ScopeValue>>({ dev: 'default', staging: 'on', prod: 'default' });
  return (
    <PreviewPageLayout title="Workspace" description="The name, address and defaults every team in this workspace inherits">
      <SettingCard id="name" title="Workspace name" description="The name people see in the header and in emails." help="Please use 32 characters at maximum." onSave={() => mockSave('Name')} dirty={name !== 'Harbor & Pine Bank'} locked={!admin} requiredRole="Admin">
        <Input value={name} maxLength={32} onChange={(e) => setName(e.target.value)} aria-label="Workspace name" className="w-full sm:w-1/2 bg-card" />
      </SettingCard>
      <SettingCard id="slug" title="Workspace address" description="The address people open to reach this workspace." help="Lowercase letters, digits and dashes. Changing it breaks saved links." onSave={() => mockSave('Address')} dirty={slug !== 'harborpine'} locked={!admin} requiredRole="Admin">
        <div className="w-full">
          <PrefixedInput prefix="ops.example.com/" value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} aria-label="Workspace address" />
        </div>
      </SettingCard>
      <ImageSettingCard title="Workspace logo" description="Shown beside the workspace name in the sidebar and in emails." name={name} onSave={() => mockSave('Logo')} />
      <SettingCard id="workspace-id" title="Workspace ID" description="Your workspace's identifier." help="Used when interacting with the API.">
        <div className="w-full sm:w-1/2">
          <CopyField value="ws_5e1f09a7c3b24d68" label="workspace ID" />
        </div>
      </SettingCard>
      <SettingCard id="default-model" title="Default model" description="The alias a new agent starts with." help={<span className="flex items-center gap-2">Teams may pick another when the switch is on. <SourceBadge level="Workspace" /></span>} onSave={() => mockSave('Default model')} locked={!admin} requiredRole="Admin">
        <div className="flex w-full flex-col sm:w-1/2 gap-4">
          <Combobox options={ALIASES} value={alias} onChange={setAlias} noun="aliases" />
          <InheritSwitch checked={overridable} onChange={setOverridable} id="override-default-model" />
        </div>
      </SettingCard>
      <SettingCard id="failure-alerts" title="Failure alerts" description="Tell the owner when a run fails, per environment." help="Default is on in production only." onSave={() => mockSave('Failure alerts')} locked={!admin} requiredRole="Admin">
        <div className="flex flex-col gap-4">
          <ScopeSelect scopes={[{ id: 'dev', label: 'Development' }, { id: 'staging', label: 'Staging' }, { id: 'prod', label: 'Production' }]} value={notify} onChange={setNotify} defaultIs="on" />
          <Note>A run that fails in Staging alerts its owner even when the default is off, because a person set it to On here.</Note>
        </div>
      </SettingCard>
      <GatedCard title="Audit export" description="Send the audit log to the bank's archive on a schedule." needs="the Enterprise plan" price="From $400 a month" action="Talk to us" onAction={() => mockSave('Request')} />
      <div className="flex flex-col gap-4 pt-4">
        <h2 className="text-sm font-semibold text-destructive">Danger zone</h2>
        <div id="transfer">
          <DangerCard title="Transfer ownership" description="Hand the workspace to another admin. You stay an admin." precondition="Ensure at least one more Owner is in the workspace." action="Transfer ownership" confirmName="Harbor & Pine Bank" onConfirm={() => mockSave('Transfer')} />
        </div>
        <DangerCard title="Leave workspace" description="Remove yourself from this workspace and every team in it." precondition="Ensure at least one more Owner stays." action="Leave workspace" confirmName="Harbor & Pine Bank" onConfirm={() => mockSave('Leave')} blockedReason="You are the only Owner. Transfer ownership first." />
        <div id="delete">
          <DangerCard title="Delete workspace" description="Deletes every agent, workflow, file and audit record. This cannot be undone." precondition="Ensure no run is in progress and the audit export has finished." action="Delete workspace" confirmName="Harbor & Pine Bank" onConfirm={() => mockSave('Delete')} />
        </div>
      </div>
      <Button asChild variant="link" className="w-fit px-0">
        <Link href="/preview/settings/kit">See every field these cards are made of</Link>
      </Button>
    </PreviewPageLayout>
  );
}
