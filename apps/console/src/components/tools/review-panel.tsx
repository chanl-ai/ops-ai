'use client';

import { CheckCircle2, CircleDashed, ShieldCheck, XCircle } from 'lucide-react';

import { Section } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { shortDate } from '@/lib/format';
import type { ModuleVersion, SecurityReview } from '@/lib/types/tool-modules';

import { ChangeList } from './versions-panel';

const semverCmp = (a: string, b: string) => {
  const x = a.split('.').map(Number);
  const y = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) - (y[i] ?? 0);
  return 0;
};

const DECISION = {
  approved: { label: 'Approved', icon: CheckCircle2, cls: 'text-emerald-700 dark:text-emerald-400' },
  pending: { label: 'Waiting for Security', icon: CircleDashed, cls: 'text-amber-700 dark:text-amber-400' },
  changes_requested: { label: 'Changes requested', icon: XCircle, cls: 'text-red-700 dark:text-red-400' },
} as const;

/**
 * Security reviews a module once per major version (00 A1). Minor versions within the major reuse the decision,
 * so the panel shows what changed since the reviewed version alongside the review itself.
 */
export function ReviewPanel({ major, reviews, versions, drift, onRequest, canRequest }: { major: number; reviews: SecurityReview[]; versions: ModuleVersion[]; drift: boolean; onRequest: () => void; canRequest: boolean }) {
  // `reviews` and `versions` arrive newest first. The latest review may be an open re-review; what changed is
  // measured from the last version Security approved, so only newer versions are listed.
  const current = reviews.find((r) => r.major === major);
  const approved = reviews.find((r) => r.major === major && r.decision === 'approved');
  const since = approved ? versions.filter((v) => v.major === major && v.status !== 'draft' && semverCmp(v.version, approved.version) > 0).sort((a, b) => semverCmp(b.version, a.version)) : [];
  const d = current ? DECISION[current.decision] : null;
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
                  · v{current.version} · {current.reviewer ? `${current.reviewer}, ${shortDate(current.decidedAt)}` : `requested by ${current.requestedBy}, ${shortDate(current.requestedAt)}`}
                </span>
              </p>
              {drift && <p className="text-sm text-amber-700 dark:text-amber-400">The MCP server now lists tools that are not in the reviewed snapshot. The gateway refuses them until a re-review.</p>}
              {current.note && <p className="text-sm">{current.note}</p>}
              {current.findings.length > 0 && (
                <div>
                  <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Findings</p>
                  <ul className="mt-1 list-disc pl-5 text-sm">
                    {current.findings.map((f) => (
                      <li key={f}>{f}</li>
                    ))}
                  </ul>
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
        <ul className="divide-y">
          {reviews.map((r) => {
            const x = DECISION[r.decision];
            return (
              <li key={r.id} className="flex items-start gap-2 px-4 py-3">
                <x.icon className={`mt-0.5 size-4 shrink-0 ${x.cls}`} />
                <div className="min-w-0 text-sm">
                  <p className="font-medium">
                    Major {r.major} · v{r.version}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {x.label}
                    {r.reviewer ? ` by ${r.reviewer}` : ''} · {shortDate(r.decidedAt ?? r.requestedAt)}
                  </p>
                </div>
              </li>
            );
          })}
          {!reviews.length && <li className="px-4 py-6 text-center text-sm text-muted-foreground">No reviews yet.</li>}
        </ul>
      </Section>
    </div>
  );
}
