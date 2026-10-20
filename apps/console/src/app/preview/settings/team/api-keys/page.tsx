'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Plus } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { PreviewPageLayout } from '@/components/settings/preview/preview-page';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { CopyField } from '@/components/shared/setting/copy-field';
import { Note } from '@/components/shared/setting/note';
import { MultiSelect } from '@/components/shared/setting/pickers';
import { RecordTable } from '@/components/shared/setting/record-table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { relativeTime } from '@/lib/format';
import { useViewerRole } from '@/lib/settings-preview-store';

import { API_KEYS, type SampleKey } from '../../_sample/data';

const COLUMNS: ColumnDef<SampleKey>[] = [
  { accessorKey: 'name', header: ({ column }) => <DataTableColumnHeader column={column} title="Key" />, cell: ({ row }) => <span className="font-medium">{row.original.name}</span>, enableHiding: false },
  { accessorKey: 'prefix', header: 'Prefix', cell: ({ row }) => <code className="font-mono text-xs">{row.original.prefix}…</code> },
  { accessorKey: 'scopes', header: 'Scopes', cell: ({ row }) => <div className="flex flex-wrap gap-1">{row.original.scopes.map((s) => <Badge key={s} variant="outline" className="font-mono text-[11px] font-normal">{s}</Badge>)}</div> },
  { accessorKey: 'team', header: 'Team' },
  { accessorKey: 'lastUsedAt', header: 'Last used', cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.lastUsedAt ? relativeTime(row.original.lastUsedAt) : 'Never'}</span> },
];
const nameOf = (k: SampleKey) => k.name;
const SCOPES = ['runs:write', 'logs:read', 'agents:read'].map((s) => ({ value: s, label: s }));

/** Team › API keys (S13): the records table (select-all, middle-truncated id), Create key in the header, and the key shown once. */
export default function ApiKeysPage() {
  const { can } = useViewerRole();
  const [open, setOpen] = React.useState(false);
  const [made, setMade] = React.useState(false);
  const [scopes, setScopes] = React.useState<string[]>([]);
  return (
    <PreviewPageLayout
      title="API keys"
      description="Keys for systems that start runs or read logs. A key is shown once, when it is created."
      actions={
        <Button onClick={() => (setMade(false), setOpen(true))} disabled={!can('Admin')}>
          <Plus className="size-4" /> Create key
        </Button>
      }
    >
      <RecordTable columns={COLUMNS} data={API_KEYS} nameOf={nameOf} searchPlaceholder="Search keys…" />
      <DialogShell
        open={open}
        onOpenChange={setOpen}
        size="md"
        title="Create key"
        description="Create a key for each system that calls Ops AI, so each can be revoked on its own."
        onSubmit={() => setMade(true)}
        footer={
          made ? (
            <Button type="button" onClick={() => setOpen(false)}>
              Done
            </Button>
          ) : (
            <>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit">Create key</Button>
            </>
          )
        }
      >
        <div className="flex flex-col gap-4">
          <FormField id="key-name" label="Name">
            <Input id="key-name" placeholder="e.g. Branch dashboard" className="bg-card" />
          </FormField>
          <FormField id="key-scopes" label="Scopes">
            <MultiSelect options={SCOPES} value={scopes} onChange={setScopes} noun="scopes" />
          </FormField>
          {made && (
            <div className="flex flex-col gap-2">
              <Note tone="warning" title="Copy it now">
                This key is shown once. Design mock: it does nothing.
              </Note>
              <CopyField value="opk_live_3c9e5a71d0b84f26e1a7" label="new key" />
            </div>
          )}
        </div>
      </DialogShell>
    </PreviewPageLayout>
  );
}
