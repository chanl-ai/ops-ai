'use client';

import * as React from 'react';

import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { CopyField } from '@/components/shared/setting/copy-field';
import { ImageSettingCard } from '@/components/shared/setting/extra-cards';
import { PrefixedInput } from '@/components/shared/setting/prefixed-input';
import { SampleData } from '@/components/shared/sample-data';
import { SettingCard } from '@/components/shared/setting/setting-card';
import { Input } from '@/components/ui/input';
import { useCanInWorkspace, useRenameWorkspace, useWorkspaceIdentity } from '@/hooks/me-queries';
import { toast } from 'sonner';

/**
 * Workspace › General: the name, address and logo every team shares. The name is platform-service's (PATCH
 * /v1/settings/workspace, workspace admins); the address and logo are not stored yet, so those cards are sample data.
 */
export default function WorkspaceGeneralPage() {
  const identity = useWorkspaceIdentity();
  // Off platform sign-in no one holds a workspace grant, so the card stays locked.
  const canRename = useCanInWorkspace('access', 'manage') === true;
  const rename = useRenameWorkspace();
  const [name, setName] = React.useState('');
  const [slug, setSlug] = React.useState('harborpine');
  React.useEffect(() => {
    if (identity?.workspace) setName(identity.workspace);
  }, [identity?.workspace]);
  const save = async () => {
    try {
      const saved = await rename.mutateAsync(name.trim());
      setName(saved.name);
      toast.success('Workspace renamed', { description: `Everyone now sees ${saved.name}.` });
    } catch (e) {
      toast.error('Couldn’t rename the workspace', { description: (e as Error).message });
    }
  };
  return (
    <SettingsPageLayout section="General" description="The name, address and logo every team in this workspace shares.">
      <SettingCard
        id="name"
        title="Workspace name"
        description="The name people see in the header and in emails."
        help="Use 80 characters at most."
        onSave={save}
        saving={rename.isPending}
        dirty={!!name.trim() && name.trim() !== identity?.workspace}
        locked={!canRename}
        requiredRole="Workspace admin"
      >
        <Input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} aria-label="Workspace name" className="w-full bg-card sm:w-1/2" disabled={!canRename} data-testid="workspace-name" />
      </SettingCard>
      <SampleData>
        <SettingCard id="slug" title="Workspace address" description="The address people open to reach this workspace." help="Lowercase letters, digits and dashes. Changing it breaks saved links." onSave={() => undefined}>
          <PrefixedInput prefix="ops.example.com/" value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} aria-label="Workspace address" />
        </SettingCard>
        <ImageSettingCard title="Workspace logo" description="Shown beside the workspace name in the sidebar and in emails." name={name || 'Workspace'} onSave={() => undefined} />
        <SettingCard id="workspace-id" title="Workspace ID" description="Your workspace's identifier." help="Used when interacting with the API.">
          <div className="w-full sm:w-1/2">
            <CopyField value="ws_5e1f09a7c3b24d68" label="workspace ID" />
          </div>
        </SettingCard>
      </SampleData>
    </SettingsPageLayout>
  );
}
