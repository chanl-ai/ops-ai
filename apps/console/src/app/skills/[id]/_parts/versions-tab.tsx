'use client';

import * as React from 'react';
import Link from 'next/link';
import { Download, GitCompare, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { VersionDiffDialog } from '@/components/skills/skill-dialogs';
import { EditClassBadge, VERSION_STATE_LABEL } from '@/components/skills/skill-meta';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useRestoreSkill } from '@/hooks/skill-queries';
import { relativeTime } from '@/lib/format';
import type { SkillDetail, SkillVersion } from '@/lib/types/skills';
import { cn } from '@/lib/utils';

const STATE_CLS: Record<SkillVersion['state'], string> = {
  published: 'bg-success/10 text-success-text border-success/40',
  in_review: 'bg-sky-500/10 text-sky-700 border-sky-500/30 dark:text-sky-300',
  draft: 'bg-muted text-muted-foreground',
  superseded: 'bg-transparent text-muted-foreground',
  deprecated: 'bg-warning/10 text-warning-text border-warning/40',
  rejected: 'bg-destructive/10 text-destructive border-destructive/40',
};

/** Every version with its state, edit class, test run and review. Compare any two; restoring copies one into a new draft. */
export function VersionsTab({ skill: s, onExport }: { skill: SkillDetail; onExport: (version: number) => void }) {
  const restore = useRestoreSkill(s.id);
  const [diff, setDiff] = React.useState<{ from: number; to: number } | null>(null);
  const [restoring, setRestoring] = React.useState<SkillVersion | null>(null);
  const newest = s.versions[0];

  return (
    <div className="flex flex-col gap-3" data-testid="skill-versions-tab">
      <ol className="relative flex flex-col gap-3 border-l pl-6">
        {s.versions.map((v, i) => {
          const prev = s.versions[i + 1];
          return (
            <li key={v.version} className="relative" data-testid="skill-version-row">
              <span className={cn('absolute top-4 -left-[29px] size-2.5 rounded-full border-2 border-background', v.state === 'published' ? 'bg-success' : v.state === 'in_review' ? 'bg-sky-500' : 'bg-muted-foreground/40')} />
              <div className="flex flex-wrap items-start gap-3 rounded-lg border bg-card p-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold">v{v.version}</span>
                    <Badge variant="outline" className={cn('h-5 px-1.5 text-[10px]', STATE_CLS[v.state])}>
                      {VERSION_STATE_LABEL[v.state]}
                    </Badge>
                    <EditClassBadge editClass={v.editClass} />
                    <span className="text-sm font-medium">{v.note}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Saved by {v.savedBy} · {relativeTime(v.savedAt)}
                    {v.publishedAt && ` · published ${relativeTime(v.publishedAt)} by ${v.publishedBy}`} · {v.tokens.toLocaleString('en-CA')} tokens
                  </p>
                  <p className="mt-0.5 text-xs">
                    {v.testRun ? (
                      <span className={v.testRun.passed === v.testRun.total ? 'text-success-text' : 'text-warning-text'}>
                        Tests {v.testRun.passed}/{v.testRun.total}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">Not tested</span>
                    )}
                    {v.reviewId && (
                      <>
                        {' · '}
                        <Link href={`/reviews?review=${v.reviewId}`} className="underline underline-offset-2">
                          {v.reviewId}
                        </Link>
                      </>
                    )}
                  </p>
                  {v.changes.length > 0 && (
                    <ul className="mt-2 list-disc pl-4 text-xs text-muted-foreground">
                      {v.changes.map((c) => (
                        <li key={c}>{c}</li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {prev && (
                    <Button variant="outline" size="sm" onClick={() => setDiff({ from: prev.version, to: v.version })} data-testid="compare-version">
                      <GitCompare className="size-3.5" /> Compare with v{prev.version}
                    </Button>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => onExport(v.version)} aria-label={`Export v${v.version}`}>
                    <Download className="size-3.5" />
                  </Button>
                  {v.version !== newest.version && (
                    <Button variant="ghost" size="sm" onClick={() => setRestoring(v)} disabled={newest.state === 'in_review' || s.status === 'deprecated'}>
                      <RotateCcw className="size-3.5" /> Restore
                    </Button>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
      <VersionDiffDialog open={!!diff} onOpenChange={(o) => !o && setDiff(null)} versions={s.versions} from={diff?.from ?? 1} to={diff?.to ?? 1} onChange={(from, to) => setDiff({ from, to })} />
      <DialogShell
        open={!!restoring}
        onOpenChange={(o) => !o && setRestoring(null)}
        size="sm"
        title={`Restore v${restoring?.version} as a draft?`}
        description={`Copies v${restoring?.version} into ${newest.state === 'draft' ? `draft v${newest.version}, replacing its unsaved changes` : `a new draft v${newest.version + 1}`}. Nothing is published; it goes through review like any other edit.`}
        footer={
          <div className="flex w-full justify-end gap-2">
            <Button variant="outline" onClick={() => setRestoring(null)} disabled={restore.isPending}>
              Cancel
            </Button>
            <LoadingButton
              isLoading={restore.isPending}
              onClick={async () => {
                if (!restoring) return;
                try {
                  const d = await restore.mutateAsync(restoring.version);
                  toast.success(`Copied v${restoring.version} into draft v${d.versions[0].version}`, { description: 'Run the tests, then request review.' });
                  setRestoring(null);
                } catch (e) {
                  toast.error('Couldn’t restore', { description: (e as Error).message });
                }
              }}
            >
              Restore as draft
            </LoadingButton>
          </div>
        }
      >
        <p className="text-sm text-muted-foreground">v{restoring?.version}: {restoring?.note}</p>
      </DialogShell>
    </div>
  );
}
