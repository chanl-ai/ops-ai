'use client';

import Link from 'next/link';
import { CheckCircle2, CircleDashed, ShieldCheck, XCircle } from 'lucide-react';

import { Row, Rows, Section } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { shortDate } from '@/lib/format';
import type { ModuleVersion } from '@/lib/types/tool-modules';

import { ChangeList } from './versions-panel';

const semverCmp = (a: string, b: string) => {
  const x = a.split('.').map(Number);
  const y = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) - (y[i] ?? 0);
  return 0;
};

const DECISION = {
  approved: { label: 'Approved', icon: CheckCircle2, cls: 'text-success-text' },
  pending: { label: 'Waiting for Security', icon: CircleDashed, cls: 'text-warning-text' },
  declined: { label: 'Returned', icon: XCircle, cls: 'text-destructive' },
} as const;

type Decision = keyof typeof DECISION;

/** A reviewed version's outcome, from its own review fields (c-163): the review itself lives in Human Tasks. */
const decisionOf = (v: ModuleVersion): Decision => (v.status === 'in_review' ? 'pending' : v.finding ? 'declined' : 'approved');

/**
 * Security reviews a module once per major version (00 A1); the review is decided in Human Tasks (c-163). Minor
 * versions within the major reuse the decision, so the panel shows what changed since the reviewed version.
 */
export function ReviewPanel({ major, versions, drift, onRequest, canRequest }: { major: number; versions: ModuleVersion[]; drift: boolean; onRequest: () => void; canRequest: boolean }) {
  // `versions` arrive newest first; the reviewed ones carry a review id.
  const reviewed = versions.filter((v) => v.reviewId);
  const current = reviewed.find((v) => v.major === major);
  const approved = reviewed.find((v) => v.major === major && decisionOf(v) === 'approved');
  const since = approved ? versions.filter((v) => v.major === major && v.status !== 'draft' && semverCmp(v.version, approved.version) > 0).sort((a, b) => semverCmp(b.version, a.version)) : [];
  const d = current ? DECISION[decisionOf(current)] : null;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-4">
        <Section
          title={`Major version ${major}`}
          description="Covers every minor and patch release in this major."
          actions={
            <Button size="sm" variant="outline" disabled={!canRequest} onClick={onRequest}>
              <ShieldCheck className="size-4" /> {current ? 'Request re-review' : 'Request security review'}
            </Button>
          }
        >
          {!current || !d ? (
            <p className="text-sm text-muted-foreground">Not reviewed. No workflow can be approved for this module until Security approves it.</p>
          ) : (
            <div className="flex flex-col gap-3">
              <p className={`inline-flex items-center gap-1.5 text-sm font-medium ${d.cls}`}>
                <d.icon className="size-4" /> {d.label}
                <span className="font-normal text-muted-foreground">
                  · v{current.version} · {current.reviewer ? `${current.reviewer}` : `requested by ${current.publishedBy}${current.requestedAt ? `, ${shortDate(current.requestedAt)}` : ''}`}
                </span>
              </p>
              {drift && <p className="text-sm text-warning-text">The MCP server now lists tools that are not in the reviewed snapshot. The gateway refuses them until a re-review.</p>}
              {current.status === 'in_review' && (
                <Button asChild size="sm" variant="outline" className="self-start">
                  <Link href={`/reviews?review=${current.reviewId}`}>Open in Human Tasks</Link>
                </Button>
              )}
              {current.finding && (
                <div>
                  <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Finding</p>
                  <p className="mt-1 text-sm">{current.finding}</p>
                </div>
              )}
            </div>
          )}
        </Section>
        {since.length > 0 && (
          <Section title={`Changed since v${approved!.version}`} description="Versions newer than the last approved one, newest first. Minor changes: workflows take them at their next publish without a new review.">
            <div className="flex flex-col gap-4">
              {since.map((v) => (
                <div key={v.version} className="flex flex-col gap-2">
                  <p className="text-sm font-medium">
                    v{v.version} <span className="font-normal text-muted-foreground">· {v.note}</span>
                  </p>
                  <ChangeList changes={v.changes} />
                </div>
              ))}
            </div>
          </Section>
        )}
      </div>
      <Section title="Review history" flush>
        {reviewed.length ? (
          <Rows>
            {reviewed.map((v) => {
              const x = DECISION[decisionOf(v)];
              return (
                <Row
                  key={v.reviewId}
                  leading={<x.icon className={`size-4 ${x.cls}`} />}
                  title={`Major ${v.major} · v${v.version}`}
                  description={`${x.label}${v.reviewer ? ` by ${v.reviewer}` : ''}${v.requestedAt ? ` · ${shortDate(v.requestedAt)}` : ''}`}
                  href={`/reviews?review=${v.reviewId}`}
                />
              );
            })}
          </Rows>
        ) : (
          <p className="px-4 py-6 text-center text-sm text-muted-foreground">No reviews yet.</p>
        )}
      </Section>
    </div>
  );
}
