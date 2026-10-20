import Link from 'next/link';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { FieldSectionLabel } from '@/components/shared/field-row';
import { RiskBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { pct, plural, relativeTime } from '@/lib/format';
import type { AssuranceSuite } from '@/lib/types/assurance';

import { KIND_LABEL, OutcomeText } from './assurance-meta';

/** The suite's latest run case by case (candidate against live, with any reviewer label) and its draft cases. */
export function SuiteSheet({ suite, open, onOpenChange, navigation }: { suite: AssuranceSuite | null; open: boolean; onOpenChange: (o: boolean) => void; navigation?: DetailSheetNavigation }) {
  const s = suite;
  return (
    <DetailSheet
      open={open}
      onOpenChange={onOpenChange}
      testId="suite-sheet"
      scrollKey={s?.id}
      navigation={navigation}
      title={s?.asset.name ?? ''}
      description={s ? `${KIND_LABEL[s.asset.kind]} · ${s.owner}${s.lastRunAt ? ` · last run ${relativeTime(s.lastRunAt)}` : ''}` : undefined}
      tags={s && <RiskBadge risk={s.tier} />}
      footerActions={
        s && (
          <Button variant="outline" size="sm" asChild>
            <Link href={s.asset.href}>Open {KIND_LABEL[s.asset.kind].toLowerCase()}</Link>
          </Button>
        )
      }
    >
      {s && (
        <div className="flex flex-col gap-6">
          {s.drafts.length > 0 && (
            <section className="flex flex-col gap-2" data-testid="suite-drafts">
              <FieldSectionLabel>Draft cases from reviews · {s.drafts.length}</FieldSectionLabel>
              <p className="text-xs text-muted-foreground">Not run by the gate until the owner activates them.</p>
              <ul className="flex flex-col gap-2">
                {s.drafts.map((d) => (
                  <li key={d.id} className="rounded-lg border p-3 text-sm">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{d.name}</span>
                      <Badge variant="outline">Draft</Badge>
                    </div>
                    <p className="mt-1 text-muted-foreground">{d.input}</p>
                    <p className="mt-2 text-xs text-muted-foreground">
                      From <Link className="underline underline-offset-2" href={`/reviews?review=${d.reviewId}`}>{d.reviewId}</Link> by {d.createdBy} · {relativeTime(d.createdAt)}
                      {d.reason ? ` · “${d.reason}”` : ''}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section className="flex flex-col gap-2">
            <FieldSectionLabel>
              Latest run{s.candidateVersion !== null ? ` · v${s.candidateVersion}` : ''}
              {s.liveVersion !== null ? ` against live v${s.liveVersion}` : ''}
            </FieldSectionLabel>
            {s.passRate === null ? (
              <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">This suite has not run yet.</p>
            ) : (
              <>
                <p className="text-sm">
                  {pct(s.passRate)} pass{s.livePassRate !== null ? ` · live ${pct(s.livePassRate)}` : ''} · {plural(s.regressions ?? 0, 'regression')}
                </p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Case</TableHead>
                      <TableHead>Candidate</TableHead>
                      <TableHead>Live</TableHead>
                      <TableHead>Reviewer</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {s.results.map((r) => (
                      <TableRow key={r.caseId}>
                        <TableCell className="max-w-64">
                          <div className="truncate" title={r.name}>{r.name}</div>
                          {r.regression && <div className="text-xs text-destructive">Regression</div>}
                        </TableCell>
                        <TableCell><OutcomeText outcome={r.candidate} /></TableCell>
                        <TableCell><OutcomeText outcome={r.live} /></TableCell>
                        <TableCell>
                          {r.humanVerdict ? (
                            <span className={r.humanVerdict !== r.candidate ? 'font-medium text-warning-text' : undefined}>
                              <OutcomeText outcome={r.humanVerdict} />
                              {r.humanVerdict !== r.candidate && <span className="ml-1 text-xs">disagrees</span>}
                            </span>
                          ) : (
                            <span className="text-xs text-muted-foreground">Not labelled</span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </>
            )}
          </section>
        </div>
      )}
    </DetailSheet>
  );
}
