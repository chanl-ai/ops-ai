'use client';

import { FileText, LayoutTemplate, ShieldX, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { FileDownloadButton } from '@/components/files/file-actions';
import { fileIcon } from '@/components/files/file-meta';
import { EmptyState } from '@/components/shared/empty-state';
import { SettingsSection } from '@/components/shared/settings-section';
import { Row, Rows } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { useRemoveSkillResource } from '@/hooks/skill-queries';
import { bytes, relativeTime } from '@/lib/format';
import type { SkillDetail } from '@/lib/types/skills';

/** Reference files (through Files, scanned before the runtime reads them) and text templates on the newest version. */
export function ResourcesTab({ skill: s }: { skill: SkillDetail }) {
  const remove = useRemoveSkillResource(s.id);
  const newest = s.versions[0];
  const resources = newest.content.resources;
  const locked = newest.state === 'in_review' ? `v${newest.version} is waiting in Reviews.` : s.status === 'deprecated' ? 'The skill is deprecated.' : undefined;
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
                    <p className="flex items-center gap-1 text-xs text-destructive-text">
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

      {/* Adding files and templates stays out until agents-service serves /v1/skills/{id}/resources and files takes
          skill uploads. */}
    </div>
  );
}
