'use client';

import Link from 'next/link';
import { CheckCircle2, ShieldCheck, XCircle } from 'lucide-react';

import { FieldSectionLabel } from '@/components/shared/field-row';
import { RiskBadge } from '@/components/status-badges';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { plural, relativeTime } from '@/lib/format';
import type { Review } from '@/lib/types/domain';
import type { EvalVersionSummary } from '@/lib/types/evals';

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <FieldSectionLabel>{title}</FieldSectionLabel>
      {children}
    </section>
  );
}

const rate = (s: EvalVersionSummary | null) => (s ? `${s.passed} of ${s.total}` : '—');
const injection = (s: EvalVersionSummary | null) => (s ? `${s.injection.passed} of ${s.injection.total}` : '—');

/** Read-only body of an `agent_publish` review: the version, its evals against the published one, and the tier. */
export function AgentPublishBody({ review }: { review: Review }) {
  const p = review.agentPublish!;
  const open = review.status === 'pending' || review.status === 'in_review';
  return (
    <div className="flex flex-col gap-6" data-testid="agent-publish-body">
      <Section title="Agent publish request">
        <div className="rounded-lg border border-primary/25 bg-primary/5 p-4">
          <p className="text-sm font-medium">{p.note}</p>
          <p className="mt-2 text-xs text-muted-foreground">
            {p.agentName} · {p.fromVersion === null ? 'first publish, ' : `v${p.fromVersion} → `}v{p.version} · saved by {p.savedBy} · requested by {p.requestedBy}
          </p>
        </div>
      </Section>
      <Section title="Tier and approvals">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <RiskBadge risk={p.tier} />
          <span className="text-muted-foreground">{p.tierReason}</span>
        </div>
        <p className="flex items-center gap-1.5 text-sm">
          <ShieldCheck className="size-4 text-muted-foreground" /> {review.approvals.length} of {plural(p.approvalsNeeded, 'approval')}
          {p.approvalsNeeded === 2 && ' · the second from the second line'}
          {review.approvals.length > 0 && <span className="text-muted-foreground">· approved by {review.approvals.join(', ')}</span>}
        </p>
      </Section>
      <Section title="Evals">
        <Table data-testid="agent-publish-evals">
          <TableHeader>
            <TableRow>
              <TableHead />
              <TableHead>Candidate v{p.version}</TableHead>
              <TableHead>{p.fromVersion === null ? 'Published' : `Published v${p.fromVersion}`}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell className="text-muted-foreground">Cases passing</TableCell>
              <TableCell className="tabular-nums">{rate(p.candidate)}</TableCell>
              <TableCell className="tabular-nums">{rate(p.published)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell className="text-muted-foreground">Injection</TableCell>
              <TableCell className="tabular-nums">{injection(p.candidate)}</TableCell>
              <TableCell className="tabular-nums">{injection(p.published)}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell className="text-muted-foreground">Regressions</TableCell>
              <TableCell className={p.candidate?.regressions ? 'font-medium text-destructive tabular-nums' : 'tabular-nums'}>{p.candidate ? p.candidate.regressions : '—'}</TableCell>
              <TableCell className="tabular-nums text-muted-foreground">—</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        {p.candidate && <p className="text-xs text-muted-foreground">Candidate run finished {relativeTime(p.candidate.ranAt)}.</p>}
        {p.blockers.length > 0 ? (
          <ul className="flex flex-col gap-1 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" data-testid="agent-publish-blockers">
            {p.blockers.map((b) => (
              <li key={b} className="flex items-start gap-1.5">
                <XCircle className="mt-0.5 size-4 shrink-0" /> {b}
              </li>
            ))}
          </ul>
        ) : p.failing > 0 ? (
          <p className="text-sm text-warning-text">{plural(p.failing, 'eval case')} failing{open ? '. At low tier this is advisory: approving needs a reason, which is kept with the version.' : '.'}</p>
        ) : (
          <p className="flex items-center gap-1.5 text-sm text-success-text">
            <CheckCircle2 className="size-4" /> Every eval case passes on v{p.version}.
          </p>
        )}
      </Section>
      {!open && review.decisionReason && (
        <Section title="Decision">
          <p className="rounded-lg border bg-muted/40 p-3 text-sm">{review.decisionReason}</p>
        </Section>
      )}
      <p className="text-xs text-muted-foreground">
        Approving publishes v{p.version}. Workflows keep the version they pin until they are republished.{' '}
        <Link href={`/agents/${p.agentId}?tab=evals`} className="underline underline-offset-2">
          Open the agent&apos;s evals
        </Link>
        {' · '}
        <Link href="/assurance?tab=gates" className="underline underline-offset-2" data-testid="open-gate-in-assurance">
          Open gate in Assurance
        </Link>
      </p>
    </div>
  );
}
