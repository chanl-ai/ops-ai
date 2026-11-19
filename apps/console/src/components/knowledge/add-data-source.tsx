'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { FolderUp, Globe, Link2, PenLine, Plug, Send, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { AddPageDialog } from '@/components/knowledge/add-page-dialog';
import { AttachSourcesDialog } from '@/components/knowledge/attach-sources-dialog';
import { AddMenu } from '@/components/shared/add-menu';
import { AddDocumentsDialog } from '@/components/shared/add-documents-dialog';
import { AddSourceWizard } from '@/components/sources/add-source-wizard';
import { useAddDocuments, useAddPage } from '@/hooks/knowledge-queries';
import { plural } from '@/lib/format';
import type { DocumentRow, KnowledgeBaseDetail, Source } from '@/lib/types/knowledge';

type Choice = 'files' | 'folder' | 'website' | 'apps' | 'push' | 'text' | 'attach';

const ITEMS: { value: Choice; label: string; description: string; icon: React.ReactNode; group: string }[] = [
  { value: 'files', label: 'Files', description: 'PDF, Word, Excel, PowerPoint, CSV, text; many at once', icon: <Upload />, group: 'Upload' },
  { value: 'folder', label: 'A folder', description: 'Every supported file inside it', icon: <FolderUp />, group: 'Upload' },
  { value: 'website', label: 'Website or sitemap', description: 'Pages of one site, refreshed on a schedule', icon: <Globe />, group: 'Sync' },
  { value: 'apps', label: 'From your apps', description: 'Knowledge from the apps your team turned on', icon: <Plug />, group: 'Sync' },
  { value: 'push', label: 'Pushed by API', description: 'Sent by your systems', icon: <Send />, group: 'Sync' },
  { value: 'text', label: 'Typed text', description: 'Write or paste a page', icon: <PenLine />, group: 'Write' },
  { value: 'attach', label: 'Attach an existing source', description: 'One already feeding another base', icon: <Link2 />, group: 'Existing' },
];

/**
 * The knowledge base's one "Add data source" menu and every dialog it opens: files or a folder (Add files), a website,
 * an app or a push source (Add source, the website and push kinds skip to step 2), typed text (Add page) and an
 * existing source (Attach). The Documents and Sources tabs both render `menu` and `dialogs`; `addFiles` opens Add files
 * with files dropped on the page.
 */
export function useAddDataSource(kb: KnowledgeBaseDetail, on?: { pageAdded?: (d: DocumentRow) => void; sourceCreated?: (s: Source) => void }) {
  const router = useRouter();
  const addDocuments = useAddDocuments(kb.id);
  const addPage = useAddPage(kb.id);
  const [open, setOpen] = React.useState<Choice | null>(null);
  const [dropped, setDropped] = React.useState<File[] | undefined>();
  // A new Add files dialog per opening, so each drop or folder choice starts with its own list.
  const [opening, setOpening] = React.useState(0);
  const show = (c: Choice) => {
    if (c === 'files' || c === 'folder') setOpening((n) => n + 1);
    setDropped(undefined);
    setOpen(c);
  };
  const close = (o: boolean) => !o && setOpen(null);

  const addFiles = React.useCallback((files: File[]) => {
    setOpening((n) => n + 1);
    setDropped(files);
    setOpen('files');
  }, []);

  const menu = <AddMenu label="Add data source" variant="primary" align="end" items={ITEMS.map((i) => ({ ...i, testId: `kb-add-${i.value}` }))} onSelect={(v) => show(v as Choice)} testId="kb-add-source" />;

  const filesOpen = open === 'files' || open === 'folder';
  const dialogs = (
    <>
      <AddDocumentsDialog
        key={opening}
        open={filesOpen}
        onOpenChange={close}
        title="Add files"
        description={`Each file is stored in Files and indexed into ${kb.name}. A file that cannot be read is listed; the rest still go in.`}
        purpose="knowledge_source"
        noun="file"
        folder
        uploadTitle="Drop files or a folder here, or choose files"
        initialFiles={dropped}
        startWith={open === 'folder' ? 'folder' : undefined}
        isPending={addDocuments.isPending}
        onSubmit={async (fileIds) => {
          const r = await addDocuments.mutateAsync(fileIds);
          const failed = r.run.counts.failed ?? 0;
          toast.success(`Added ${plural(r.files.length, 'file')} to ${kb.name}`, { description: failed ? `${plural(failed, 'file')} could not be read; the Documents tab says why.` : 'Indexed; agents can cite them now.' });
          setOpen(null);
        }}
      />
      <AddPageDialog
        open={open === 'text'}
        onOpenChange={close}
        saving={addPage.isPending}
        onSubmit={(input) =>
          addPage.mutateAsync(input).then((d) => {
            on?.pageAdded?.(d);
            toast.success(`Added ${d.title}`, { description: d.status === 'indexed' ? 'Indexed; agents can cite it now.' : d.error });
          })
        }
      />
      <AddSourceWizard
        open={open === 'website' || open === 'apps' || open === 'push'}
        onOpenChange={close}
        kb={kb}
        initialKind={open === 'website' ? 'site' : open === 'push' ? 'push' : undefined}
        onCreated={(s, approval) => {
          on?.sourceCreated?.(s);
          toast.success(`${s.name} created`, {
            description:
              approval.state === 'waiting'
                ? `First sync started. Its questions and FAQ steps wait for the knowledge owner’s approval: ${approval.reason}`
                : approval.state === 'approved'
                  ? 'First sync started, with its questions and FAQ steps approved.'
                  : 'First sync started.',
            action: { label: 'View source', onClick: () => router.push(`/data/sources/${s.id}`) },
          });
        }}
      />
      <AttachSourcesDialog open={open === 'attach'} onOpenChange={close} kb={kb} />
    </>
  );

  return { menu, dialogs, addFiles, show };
}

