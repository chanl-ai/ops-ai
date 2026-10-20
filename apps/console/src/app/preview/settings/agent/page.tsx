'use client';

import * as React from 'react';

import { ModelAliasForm } from '@/components/settings/preview/model-alias-form';
import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { CopyField } from '@/components/shared/setting/copy-field';
import { DangerCard } from '@/components/shared/setting/danger-card';
import { SourceBadge } from '@/components/shared/setting/inherit-switch';
import { Note } from '@/components/shared/setting/note';
import { Combobox, MultiSelect } from '@/components/shared/setting/pickers';
import { ScrollTabsList } from '@/components/shared/setting/scroll-tabs';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { SplitView } from '@/components/shared/setting/split-view';
import { UsageBar } from '@/components/shared/setting/usage-bar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { usePreviewStore, useViewerRole } from '@/lib/settings-preview-store';

import { mockSave } from '../_sample/save';

const TABS = ['Overview', 'Settings', 'Deployments', 'Versions', 'Test chat', 'Runs and history', 'Knowledge and tools', 'Permissions and access'].map((t) => ({ value: t.toLowerCase().replace(/\W+/g, '-'), label: t }));
const TOOLS = ['get_statement', 'place_hold', 'search_policy', 'send_email'].map((t) => ({ value: t, label: t }));

/**
 * An agent's own Settings tab, built from the same cards: identity, instructions beside a live preview (resizable),
 * model with the Model alias dialog opened in place, limits, and the danger zone last.
 */
export default function AgentSettingsPage() {
  const { can } = useViewerRole();
  const builder = can('Builder');
  const aliases = usePreviewStore((s) => s.aliases);
  const [name, setName] = React.useState('Branch advisor');
  const [instructions, setInstructions] = React.useState('Answer from the branch manual. If the manual does not say, say you do not know and offer a person.');
  const [alias, setAlias] = React.useState<string | null>('advisor-default');
  const [dialog, setDialog] = React.useState(false);
  const [tools, setTools] = React.useState<string[]>(['get_statement', 'search_policy']);
  const options = aliases.map((a) => ({ value: a.alias, label: a.alias, hint: a.model }));
  return (
    <PreviewPageLayout
      title="Branch advisor"
      description="An agent's Settings tab, built from the same cards as the pages around it"
      actions={
        <Button variant="outline" onClick={() => mockSave('Version')} disabled={!builder}>
          Save as v6
        </Button>
      }
    >
      <Tabs defaultValue="settings" className="gap-4">
        <ScrollTabsList tabs={TABS} />
        <TabsContent value="settings" className="flex flex-col gap-6">
          <SettingCard id="identity" title="Identity" description="The name people and workflows call this agent." help="Please use 40 characters at maximum." onSave={() => mockSave('Identity')} dirty={name !== 'Branch advisor'} locked={!builder} requiredRole="Builder">
            <Input value={name} maxLength={40} onChange={(e) => setName(e.target.value)} aria-label="Agent name" className="w-full sm:w-1/2 bg-card" />
          </SettingCard>
          <div id="instructions" className="scroll-mt-20">
            <SplitView
              id="agent-instructions"
              left={
                <div className="flex h-full flex-col gap-2">
                  <h3 className="text-sm font-semibold">Instructions</h3>
                  <Textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} aria-label="Instructions" className="min-h-48 flex-1 bg-card" />
                  <Button size="sm" className="self-start" onClick={() => mockSave('Instructions')} disabled={!builder}>
                    Save
                  </Button>
                </div>
              }
              right={
                <div className="flex flex-col gap-2">
                  <h3 className="text-sm font-semibold">What the model reads</h3>
                  <pre className="whitespace-pre-wrap rounded-md border bg-muted/40 p-3 text-xs">{`System\n${instructions}\n\nTools\n${tools.join(', ') || 'none'}`}</pre>
                </div>
              }
            />
          </div>
          <SettingCard id="model" title="Model" description="The alias this agent calls. The model behind it can change without editing the agent." help={<span className="flex items-center gap-2">Aliases are set under Govern › Models. <SourceBadge level="Workspace" /></span>} onSave={() => mockSave('Model')} dirty={alias !== 'advisor-default'} locked={!builder} requiredRole="Builder">
            <div className="flex w-full flex-col sm:w-1/2 gap-3">
              <Combobox options={options} value={alias} onChange={setAlias} noun="aliases" />
              <Button type="button" variant="link" className="w-fit px-0" onClick={() => setDialog(true)} disabled={!can('Admin')}>
                Need another alias? Create one here
              </Button>
            </div>
          </SettingCard>
          <SettingCard id="capabilities" title="Tools" description="What this agent may call." help="A write tool still waits for a person where a gate says so." onSave={() => mockSave('Tools')} locked={!builder} requiredRole="Builder">
            <div className="w-full sm:w-1/2">
              <MultiSelect options={TOOLS} value={tools} onChange={setTools} noun="tools" />
            </div>
          </SettingCard>
          <SettingCard id="limits" title="Limits" description="The most one run may spend." help={<span className="flex items-center gap-2">Conversation caps come from Govern › Models. <SourceBadge level="Workspace" /></span>} onSave={() => mockSave('Limits')} locked={!builder} requiredRole="Builder">
            <div className="flex w-full flex-col sm:w-1/2 gap-4">
              <Input defaultValue="2.50" aria-label="USD ceiling per run" className="w-32 bg-card" />
              <UsageBar label="This week's spend" used={38} limit={50} format={(n) => `$${n}`} />
            </div>
          </SettingCard>
          <SettingCard id="agent-id" title="Agent ID" description="Used by workflows, the API and the audit log." help="Used when interacting with the API.">
            <div className="w-full sm:w-1/2">
              <CopyField value="ag_advisor_9f3a41c27b" label="agent ID" />
            </div>
          </SettingCard>
          <Note>Deployments have their own tab, so embedding the agent in a page is not on this one.</Note>
          <div id="danger" className="flex scroll-mt-20 flex-col gap-4">
            <h2 className="text-sm font-semibold text-destructive">Danger zone</h2>
            <DangerCard title="Pause agent" description="New runs stop. Runs in progress finish." precondition="Workflows that call it will wait or fail, as each is set." action="Pause agent" confirmName="Branch advisor" onConfirm={() => mockSave('Pause')} />
            <DangerCard title="Delete agent" description="Removes the agent and its version history." precondition="Ensure no published workflow uses it." action="Delete agent" confirmName="Branch advisor" onConfirm={() => mockSave('Delete')} blockedReason="2 published workflows use it." />
          </div>
        </TabsContent>
      </Tabs>
      <ModelAliasForm shell="dialog" open={dialog} onOpenChange={setDialog} onAdded={(a) => setAlias(a)} />
    </PreviewPageLayout>
  );
}
