'use client';

import * as React from 'react';
import { notFound } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { BookOpen, FileText, Link2, Settings2, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableRowActions } from '@/components/data-table-row-actions';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { ItemStatusBadge, MimeIcon } from '@/components/knowledge/knowledge-meta';
import { PageLayout } from '@/components/page-layout';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FileUpload } from '@/components/shared/file-upload';
import { StopRowClick } from '@/components/shared/form-field';
import { FormField } from '@/components/shared/form-field';
import { Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { relativeTime } from '@/lib/format';

import { BASE, DOCS, PRESETS, type PreviewDoc } from './sample';

/**
 * The c-159 preview: a knowledge base with one "Add documents" area (drop a file, paste text, add a link) that syncs on
 * its own, documents with Replace and Remove, and ingestion presets in settings. Mock data, dev server only, not in the
 * nav; nothing here calls a service.
 */
export default function KnowledgeSimplePreview() {
  if (process.env.NODE_ENV !== 'development') notFound();
  return <Preview />;
}

function Preview() {
  const [docs, setDocs] = React.useState<PreviewDoc[]>(DOCS);
  const [removing, setRemoving] = React.useState<PreviewDoc | null>(null);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [preset, setPreset] = React.useState('standard');
  const [textTitle, setTextTitle] = React.useState('');
  const [text, setText] = React.useState('');
  const [link, setLink] = React.useState('');
  const replaceRef = React.useRef<HTMLInputElement>(null);
  const [replacing, setReplacing] = React.useState<PreviewDoc | null>(null);

  // Adding is the whole flow: the document appears indexing and turns indexed, with no source or sync step.
  const add = (d: Omit<PreviewDoc, 'id' | 'status' | 'version' | 'updatedAt' | 'citedBy'>) => {
    const id = `d${Date.now()}`;
    setDocs((all) => [{ ...d, id, status: 'processing', version: 1, updatedAt: new Date().toISOString(), citedBy: [] }, ...all]);
    setTimeout(() => setDocs((all) => all.map((x) => (x.id === id ? { ...x, status: 'indexed' } : x))), 1500);
    toast.success(`Added ${d.name}`, { description: 'It is being read now; agents can cite it in a moment.' });
  };
  const replace = (doc: PreviewDoc, file: File) => {
    setDocs((all) => all.map((x) => (x.id === doc.id ? { ...x, name: file.name, status: 'processing', version: x.version + 1, updatedAt: new Date().toISOString() } : x)));
    setTimeout(() => setDocs((all) => all.map((x) => (x.id === doc.id ? { ...x, status: 'indexed' } : x))), 1500);
    toast.success(`Replaced ${doc.name}`, { description: `Now v${doc.version + 1}. Agents cite the new version from the next answer.` });
  };

  const columns = React.useMemo<ColumnDef<PreviewDoc>[]>(
    () => [
      {
        accessorKey: 'name',
        header: ({ column }) => <DataTableColumnHeader column={column} title="Document" />,
        cell: ({ row }) => (
          <span className="flex min-w-0 items-center gap-2">
            <MimeIcon mime={row.original.mime} />
            <span className="truncate font-medium">{row.original.name}</span>
            <span className="shrink-0 text-xs text-muted-foreground">v{row.original.version}</span>
          </span>
        ),
      },
      { accessorKey: 'status', header: ({ column }) => <DataTableColumnHeader column={column} title="Status" />, cell: ({ row }) => <ItemStatusBadge status={row.original.status} /> },
      {
        id: 'citedBy',
        accessorFn: (d) => d.citedBy.length,
        header: ({ column }) => <DataTableColumnHeader column={column} title="Cited by" />,
        cell: ({ row }) => (row.original.citedBy.length ? <span className="text-sm">{row.original.citedBy.join(', ')}</span> : <span className="text-sm text-muted-foreground">No agent</span>),
      },
      { accessorKey: 'updatedAt', header: ({ column }) => <DataTableColumnHeader column={column} title="Updated" />, cell: ({ row }) => <span className="text-sm text-muted-foreground">{relativeTime(row.original.updatedAt)}</span> },
      {
        id: 'actions',
        enableHiding: false,
        cell: ({ row }) => (
          <StopRowClick>
            <DataTableRowActions
              row={row}
              actions={[
                { label: 'Replace file', icon: Upload, onClick: (r) => (setReplacing(r.original), replaceRef.current?.click()) },
                { label: 'Remove', icon: FileText, variant: 'destructive', onClick: (r) => setRemoving(r.original) },
              ]}
            />
          </StopRowClick>
        ),
      },
    ],
    [],
  );

  return (
    <PageLayout
      icon={BookOpen}
      title={BASE.name}
      description={BASE.description}
      badge={<Badge variant="outline">Preview · c-159</Badge>}
      actions={
        <Button variant="outline" onClick={() => setSettingsOpen(true)}>
          <Settings2 className="size-4" /> Settings
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <Section title="Add documents" description="Each document is read and indexed as soon as it is added. Agents that use this knowledge base can cite it in a moment.">
          <Tabs defaultValue="file">
            <TabsList>
              <TabsTrigger value="file">
                <Upload className="size-3.5" /> Upload files
              </TabsTrigger>
              <TabsTrigger value="text">
                <FileText className="size-3.5" /> Paste text
              </TabsTrigger>
              <TabsTrigger value="link">
                <Link2 className="size-3.5" /> Add a link
              </TabsTrigger>
            </TabsList>
            <TabsContent value="file" className="pt-3">
              <FileUpload
                purpose="knowledge_source"
                multiple
                title="Drop files here or browse"
                upload={async (file) => (add({ name: file.name, mime: file.type || 'application/octet-stream', kind: 'file' }), { fileId: `fil_${Date.now()}` })}
                onChange={() => undefined}
                testId="add-documents-files"
              />
            </TabsContent>
            <TabsContent value="text" className="flex flex-col gap-3 pt-3">
              <FormField id="doc-title" label="Title">
                <Input id="doc-title" value={textTitle} onChange={(e) => setTextTitle(e.target.value)} placeholder="e.g. Deferral FAQ" />
              </FormField>
              <FormField id="doc-text" label="Text">
                <Textarea id="doc-text" rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the text agents should answer from." />
              </FormField>
              <Button className="self-start" disabled={!textTitle.trim() || !text.trim()} onClick={() => (add({ name: textTitle.trim(), mime: 'text/plain', kind: 'text' }), setTextTitle(''), setText(''))}>
                Add text
              </Button>
            </TabsContent>
            <TabsContent value="link" className="flex flex-col gap-3 pt-3">
              <FormField id="doc-link" label="Page address" hint="A public https page. The page is read once now and again each night.">
                <Input id="doc-link" value={link} onChange={(e) => setLink(e.target.value)} placeholder="https://northfieldbank.com/mortgages/rates" />
              </FormField>
              <Button className="self-start" disabled={!/^https:\/\/\S+\.\S+/.test(link.trim())} onClick={() => (add({ name: link.trim().replace(/^https:\/\//, ''), mime: 'text/html', kind: 'link' }), setLink(''))}>
                Add link
              </Button>
            </TabsContent>
          </Tabs>
        </Section>

        <DataTableWithViews columns={columns} data={docs} getRowId={(d) => d.id} searchColumn="name" searchPlaceholder="Search documents…" hideViewSwitcher />
      </div>

      <input
        ref={replaceRef}
        type="file"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file && replacing) replace(replacing, file);
          e.target.value = '';
          setReplacing(null);
        }}
      />

      <DeleteDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        entityType="document"
        entityName={removing?.name}
        verb="Remove"
        description={removing?.citedBy.length ? 'Agents stop citing it from their next answer.' : 'No agent cites it.'}
        onConfirm={() => {
          if (!removing) return;
          setDocs((all) => all.filter((x) => x.id !== removing.id));
          toast.success(`Removed ${removing.name}`);
          setRemoving(null);
        }}
      >
        {!!removing?.citedBy.length && (
          <div className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning-text">Cited by {removing.citedBy.join(', ')}.</div>
        )}
      </DeleteDialog>

      <DialogShell
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        size="md"
        title="Knowledge base settings"
        description="How documents are read. Applies to every document added from now on."
        onSubmit={() => (setSettingsOpen(false), toast.success('Saved settings'))}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setSettingsOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Save</Button>
          </div>
        }
      >
        <FormField id="kb-preset" label="Reading preset">
          <RadioGroup id="kb-preset" value={preset} onValueChange={setPreset} className="flex flex-col gap-2">
            {PRESETS.map((p) => (
              <label key={p.id} htmlFor={`preset-${p.id}`} className="flex cursor-pointer items-start gap-3 rounded-lg border p-3">
                <RadioGroupItem id={`preset-${p.id}`} value={p.id} className="mt-0.5" />
                <span className="flex flex-col">
                  <span className="text-sm font-medium">{p.name}</span>
                  <span className="text-xs text-muted-foreground">{p.detail}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
        </FormField>
      </DialogShell>
    </PageLayout>
  );
}
