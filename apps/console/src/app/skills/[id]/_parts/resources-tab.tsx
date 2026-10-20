'use client';

import * as React from 'react';
import { FileText, LayoutTemplate, Plus, ShieldX, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { FileDownloadButton } from '@/components/files/file-actions';
import { fileIcon } from '@/components/files/file-meta';
import { EmptyState } from '@/components/shared/empty-state';
import { FileUpload, type UploadItem, uploadsBlocker, uploadsReady } from '@/components/shared/file-upload';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { Row, Rows } from '@/components/shared/surface';
import { TemplateResourceDialog } from '@/components/skills/skill-dialogs';
import { Button } from '@/components/ui/button';
import { useAddSkillResource, useRemoveSkillResource } from '@/hooks/skill-queries';
import { bytes, plural, relativeTime } from '@/lib/format';
import type { SkillDetail } from '@/lib/types/skills';

/** Reference files (through Files, scanned before the runtime reads them) and text templates on the newest version. */
export function ResourcesTab({ skill: s }: { skill: SkillDetail }) {
  const add = useAddSkillResource(s.id);
  const remove = useRemoveSkillResource(s.id);
  const [uploads, setUploads] = React.useState<UploadItem[]>([]);
  const [uploadKey, setUploadKey] = React.useState(0);
  const [templateOpen, setTemplateOpen] = React.useState(false);
  const newest = s.versions[0];
  const resources = newest.content.resources;
  const locked = newest.state === 'in_review' ? `v${newest.version} is waiting in Reviews.` : s.status === 'deprecated' ? 'The skill is deprecated.' : undefined;
  const ready = uploadsReady(uploads);
  const waiting = uploads.length ? uploadsBlocker(uploads) : undefined;
  const target = newest.state === 'draft' ? `draft v${newest.version}` : `a new draft v${newest.version + 1}`;

  return (
    <div className="flex flex-col gap-4" data-testid="skill-resources-tab">
      <SettingsSection title={`Files and templates · ${resources.length}`} description={`Changes go to ${target} and need two reviewers before agents see them.`}>
        {resources.length ? (
          <Rows className="rounded-md border bg-card">
            {resources.map((r) => {
              const Icon = r.kind === 'template' ? LayoutTemplate : fileIcon(r.name);
              return (
                <Row
                  key={r.id}
                  wrap
                  leading={<Icon className="mt-0.5 size-4 text-muted-foreground" />}
                  title={
                    <span className="flex items-center gap-2">
                      <span className="truncate">{r.name}</span>
                      <span className="text-xs font-normal text-muted-foreground">{r.kind === 'template' ? 'Template' : r.size ? bytes(r.size) : 'File'}</span>
                    </span>
                  }
                  description={r.description}
                  trailing={
                    <>
                      {r.fileId && <FileDownloadButton fileId={r.fileId} name={r.name} blocked={r.blocked} size="icon" variant="ghost" />}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7"
                        disabled={!!locked || remove.isPending}
                        aria-label={`Remove ${r.name}`}
                        onClick={() =>
                          remove.mutate(r.id, {
                            onSuccess: (d) => toast.success(`Removed ${r.name}`, { description: `Saved to draft v${d.versions[0].version}.` }),
                            onError: (e) => toast.error('Couldn’t remove it', { description: e.message }),
                          })
                        }
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </>
                  }
                >
                  {r.blocked && (
                    <p className="flex items-center gap-1 text-xs text-destructive">
                      <ShieldX className="size-3" /> {r.blocked} The skill loads without it.
                    </p>
                  )}
                  {r.body && <pre className="mt-1 max-h-28 overflow-auto rounded bg-muted/50 p-2 font-mono text-[11px] whitespace-pre-wrap">{r.body}</pre>}
                  <p className="text-[11px] text-muted-foreground">
                    Added by {r.addedBy} · {relativeTime(r.addedAt)}
                  </p>
                </Row>
              );
            })}
          </Rows>
        ) : (
          <EmptyState icon={FileText} title="No files or templates" description="Add the procedure the steps follow, a reference table or a reply template." />
        )}
      </SettingsSection>

      <SettingsSection title="Add" description="Files are stored through Files and scanned before the runtime reads them.">
        <div className="flex flex-col gap-3">
          <FileUpload key={uploadKey} id="skill-resource-upload" purpose="skill_resource" multiple disabled={!!locked} onChange={setUploads} testId="skill-resource-upload" />
          <div className="flex flex-wrap items-center gap-2">
            <LoadingButton
              size="sm"
              isLoading={add.isPending}
              disabled={!!locked || !ready}
              onClick={() =>
                add.mutate(
                  { fileIds: uploads.map((u) => u.fileId!) },
                  {
                    onSuccess: (d) => {
                      toast.success(`Added ${plural(uploads.length, 'file')}`, { description: `Saved to draft v${d.versions[0].version}.` });
                      setUploads([]);
                      setUploadKey((k) => k + 1);
                    },
                    onError: (e) => toast.error('Couldn’t add the files', { description: e.message }),
                  },
                )
              }
              data-testid="skill-resource-add"
            >
              <Plus className="size-3.5" /> Add {uploads.length ? plural(uploads.length, 'file') : 'files'}
            </LoadingButton>
            <Button variant="outline" size="sm" disabled={!!locked} onClick={() => setTemplateOpen(true)}>
              <LayoutTemplate className="size-3.5" /> Add template
            </Button>
            {(locked || waiting) && <span className="text-xs text-muted-foreground">{locked ?? waiting}</span>}
          </div>
        </div>
      </SettingsSection>
      <TemplateResourceDialog
        open={templateOpen}
        onOpenChange={setTemplateOpen}
        isPending={add.isPending}
        onSubmit={async (template) => {
          const d = await add.mutateAsync({ template });
          toast.success(`Added ${template.name}`, { description: `Saved to draft v${d.versions[0].version}.` });
        }}
      />
    </div>
  );
}
