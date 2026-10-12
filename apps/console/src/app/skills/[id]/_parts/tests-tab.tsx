'use client';

import * as React from 'react';
import { CheckCircle2, ListChecks, Pencil, Play, Plus, Trash2, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import { CheckChips, OutcomeText } from '@/components/evals/eval-meta';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { SkillTestDialog } from '@/components/skills/skill-test-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useAddSkillTest, useRemoveSkillTest, useRunSkillTests, useUpdateSkillTest } from '@/hooks/skill-queries';
import { ms, plural, relativeTime } from '@/lib/format';
import type { SkillDetail, SkillTestCase, SkillTestRun } from '@/lib/types/skills';
import { cn } from '@/lib/utils';

const SOURCE: Record<SkillTestCase['source'], string> = { generated: 'Generated', manual: 'Manual', case: 'From a case', document: 'From a document', imported: 'Imported' };

/** Test cases (agent eval checks) and runs. A run on the newest version is required before review. */
export function TestsTab({ skill: s }: { skill: SkillDetail }) {
  const add = useAddSkillTest(s.id);
  const update = useUpdateSkillTest(s.id);
  const remove = useRemoveSkillTest(s.id);
  const run = useRunSkillTests(s.id);
  const [editing, setEditing] = React.useState<SkillTestCase | 'new' | null>(null);
  const [deleting, setDeleting] = React.useState<SkillTestCase | null>(null);
  const [openRun, setOpenRun] = React.useState<string | null>(s.runs[0]?.id ?? null);
  const newest = s.versions[0];
  const latestOnNewest = s.runs.find((r) => r.version === newest.version);
  const shown = s.runs.find((r) => r.id === openRun) ?? s.runs[0];
  const toolNames = s.content.tools.map((t) => t.name);

  return (
    <div className="flex flex-col gap-4" data-testid="skill-tests-tab">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-3">
        {latestOnNewest ? (
          latestOnNewest.passed === latestOnNewest.total ? (
            <CheckCircle2 className="size-5 text-success-text" />
          ) : (
            <XCircle className="size-5 text-warning-text" />
          )
        ) : (
          <ListChecks className="size-5 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1 text-sm">
          {latestOnNewest ? (
            <>
              <span className="font-medium">
                {latestOnNewest.passed} of {plural(latestOnNewest.total, 'case')} pass on v{newest.version}
              </span>
              <span className="text-muted-foreground">
                {' '}
                · {relativeTime(latestOnNewest.ranAt)} by {latestOnNewest.ranBy}
              </span>
            </>
          ) : (
            <span>No run on v{newest.version} yet. Run the tests before requesting review.</span>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={() => setEditing('new')}>
          <Plus className="size-3.5" /> Add case
        </Button>
        <LoadingButton
          size="sm"
          isLoading={run.isPending}
          disabled={!s.tests.length}
          onClick={() =>
            run.mutate(undefined, {
              onSuccess: (r) => {
                setOpenRun(r.id);
                toast[r.passed === r.total ? 'success' : 'warning'](`${r.passed} of ${plural(r.total, 'case')} pass on v${r.version}`, { description: r.passed === r.total ? 'Ready to request review.' : 'A reviewer must give a reason to publish with failures.' });
              },
              onError: (e) => toast.error('Couldn’t run the tests', { description: e.message }),
            })
          }
          data-testid="run-skill-tests"
        >
          <Play className="size-3.5" /> Run tests
        </LoadingButton>
      </div>

      <SettingsSection title={`Cases · ${s.tests.length}`} description="Each input must make the runtime choose this skill, and the checks reuse the agent eval checks.">
        {s.tests.length ? (
          <div className="overflow-x-auto rounded-md border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Case</TableHead>
                  <TableHead>Checks</TableHead>
                  <TableHead>Last result</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.tests.map((t) => (
                  <TableRow key={t.id} data-testid="skill-test-row">
                    <TableCell className="max-w-80">
                      <div className="truncate font-medium">{t.name}</div>
                      <div className="truncate text-xs text-muted-foreground">{t.input}</div>
                    </TableCell>
                    <TableCell>
                      <CheckChips checks={t.checks} />
                    </TableCell>
                    <TableCell>
                      <OutcomeText status={t.lastOutcome} />
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap text-muted-foreground">{SOURCE[t.source]}</TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      <Button variant="ghost" size="icon" className="size-7" aria-label={`Edit ${t.name}`} onClick={() => setEditing(t)}>
                        <Pencil className="size-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="size-7" aria-label={`Delete ${t.name}`} onClick={() => setDeleting(t)}>
                        <Trash2 className="size-3.5" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <EmptyState icon={ListChecks} title="No test cases" description="Add inputs the skill should handle and what the reply must do. A version cannot go to review without them." action={{ label: 'Add case', onClick: () => setEditing('new') }} />
        )}
      </SettingsSection>

      {s.runs.length > 0 && (
        <SettingsSection title={`Runs · ${s.runs.length}`} description="Newest first. Each run is kept with the version it tested.">
          <div className="grid gap-3 lg:grid-cols-[220px_minmax(0,1fr)]">
            <ul className="flex flex-col gap-1" aria-label="Test runs">
              {s.runs.map((r) => (
                <li key={r.id}>
                  <button type="button" onClick={() => setOpenRun(r.id)} aria-current={shown?.id === r.id} className={cn('flex w-full items-center justify-between gap-2 rounded-md border bg-card px-3 py-2 text-left text-sm hover:bg-muted/40', shown?.id === r.id && 'border-primary')}>
                    <span>
                      <span className="font-mono text-xs">v{r.version}</span> <span className="text-xs text-muted-foreground">{relativeTime(r.ranAt)}</span>
                    </span>
                    <Badge variant={r.passed === r.total ? 'secondary' : 'outline'} className={cn('tabular-nums', r.passed < r.total && 'border-warning/40 text-warning-text')}>
                      {r.passed}/{r.total}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
            {shown && <RunResults run={shown} />}
          </div>
        </SettingsSection>
      )}

      <SkillTestDialog
        open={!!editing}
        onOpenChange={(o) => !o && setEditing(null)}
        initial={editing && editing !== 'new' ? { name: editing.name, input: editing.input, checks: editing.checks } : undefined}
        tools={toolNames}
        knowledgeBases={s.content.knowledgeBases}
        isPending={add.isPending || update.isPending}
        onSubmit={async (i) => {
          if (editing && editing !== 'new') await update.mutateAsync({ caseId: editing.id, input: i });
          else await add.mutateAsync({ ...i, source: 'manual' });
          toast.success(editing === 'new' ? `Added ${i.name}` : `Saved ${i.name}`, { description: 'Run the tests to see the result on the newest version.' });
        }}
      />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="test case"
        entityName={deleting?.name}
        description="Past runs keep its result."
        isLoading={remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          await remove.mutateAsync(deleting.id);
          toast.success(`Deleted ${deleting.name}`);
          setDeleting(null);
        }}
      />
    </div>
  );
}

function RunResults({ run }: { run: SkillTestRun }) {
  return (
    <div className="overflow-hidden rounded-md border bg-card" data-testid="skill-run-results">
      <div className="border-b px-3 py-2 text-xs text-muted-foreground">
        v{run.version} · {run.ranBy} · {relativeTime(run.ranAt)}
      </div>
      <ul className="divide-y">
        {run.results.map((r) => (
          <li key={r.caseId} className="flex items-start gap-2 px-3 py-2 text-sm">
            {r.status === 'pass' ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-text" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{r.caseName}</span>
                {!r.skillLoaded && <Badge variant="outline" className="border-warning/40 text-[10px] text-warning-text">Skill not chosen</Badge>}
                <span className="ml-auto text-xs text-muted-foreground tabular-nums">{ms(r.latencyMs)}</span>
              </div>
              {r.failure && <p className="text-xs text-destructive">{r.failure}</p>}
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                {r.checks.map((c) => (
                  <span key={c.label} className={c.status === 'fail' ? 'text-destructive' : 'text-muted-foreground'}>
                    {c.status === 'pass' ? '✓' : '✗'} {c.label}
                  </span>
                ))}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
