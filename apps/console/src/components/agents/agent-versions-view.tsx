'use client';

import * as React from 'react';
import Link from 'next/link';
import { GitCompare, History, Rocket, RotateCcw } from 'lucide-react';

import { EvalSummaryLine } from '@/components/evals/eval-meta';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { KeyValues, Section } from '@/components/shared/surface';
import { RestoreVersionDialog, VersionTimeline, VersionTimelineItem } from '@/components/shared/version-history';
import { AgentVersionBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useAgentPrompt } from '@/hooks/queries';
import { relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { AgentVersion } from '@/lib/types/domain';

/**
 * The agent's Versions tab: the version list on the left, the selected version's details and its prompt on the
 * right, and one footer under both with Restore, Compare and Publish for the selected version. On a phone the
 * columns stack and the footer stays under them.
 */
export function AgentVersionsView({
  agentId,
  newest,
  versions,
  isPending,
  isError,
  onRetry,
  onRestore,
  restoring,
  onPublish,
}: {
  agentId: string;
  /** The agent's newest version number. */
  newest: number;
  versions?: AgentVersion[];
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
  onRestore: (version: number) => Promise<unknown>;
  restoring: boolean;
  /** Opens the page's publish dialog; absent when this person cannot publish. */
  onPublish?: () => void;
}) {
  const [picked, setPicked] = React.useState<number | null>(null);
  const [restoreTarget, setRestoreTarget] = React.useState<AgentVersion | null>(null);
  const selected = versions?.find((v) => v.version === picked) ?? versions?.[0];
  const prompt = useAgentPrompt(agentId, selected?.version ?? newest, !!selected);

  if (isPending) return <Skeleton className="h-96 w-full rounded-lg" />;
  if (isError) return <QueryError what="version history" onRetry={onRetry} />;
  if (!versions?.length || !selected) return <EmptyState icon={History} title="No versions yet" description="Each save makes a draft; published and reviewed versions are listed here." />;

  const publishable = selected.version === newest && selected.state === 'draft' && onPublish;
  return (
    <div className="flex min-w-0 flex-col rounded-lg border bg-card" data-testid="agent-versions-view">
      <div className="grid min-w-0 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <div className="min-w-0 border-b p-4 lg:border-r lg:border-b-0">
          <VersionTimeline compact testId="version-history">
            {versions.map((v) => (
              <VersionTimelineItem key={v.version} compact dot={v.current ? 'current' : 'muted'} testId={`version-row-v${v.version}`}>
                <button
                  type="button"
                  onClick={() => setPicked(v.version)}
                  aria-current={v.version === selected.version ? 'true' : undefined}
                  className={cn('w-full rounded-md px-2 py-1 text-left hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', v.version === selected.version && 'bg-muted')}
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold">v{v.version}</span>
                    <AgentVersionBadge state={v.state} testId={`version-state-v${v.version}`} />
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {v.note || 'No note'} · {relativeTime(v.savedAt)}
                  </span>
                </button>
              </VersionTimelineItem>
            ))}
          </VersionTimeline>
        </div>
        <div className="flex min-w-0 flex-col gap-4 p-4" data-testid="version-details">
          <KeyValues
            rows={[
              ['Version', `v${selected.version}${selected.note ? `: ${selected.note}` : ''}`],
              ['Saved', `${selected.savedBy} · ${relativeTime(selected.savedAt)}`],
              ...(selected.publishedAt ? ([['Published', `${selected.publishedBy ?? ''} · ${relativeTime(selected.publishedAt)}`]] as [string, string][]) : []),
              ...(selected.decisionReason ? ([['Reviewer', selected.decisionReason]] as [string, string][]) : []),
            ]}
          />
          {selected.evalSummary && <EvalSummaryLine summary={selected.evalSummary} />}
          {selected.changes.length > 0 && (
            <Section title="What changed" bodyClassName="p-4">
              <ul className="list-disc pl-4 text-sm text-muted-foreground">
                {selected.changes.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </Section>
          )}
          <Section title="Prompt" description="What the model receives from this version, Never last." flush>
            {prompt.isPending ? (
              <Skeleton className="m-4 h-32" />
            ) : prompt.isError ? (
              <div className="p-4">
                <QueryError what="the prompt" error={prompt.error} onRetry={() => prompt.refetch()} retrying={prompt.isFetching} />
              </div>
            ) : (
              <pre className="max-h-96 overflow-auto p-4 font-mono text-xs leading-relaxed whitespace-pre-wrap" data-testid="version-prompt">
                {prompt.data.text}
              </pre>
            )}
          </Section>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t px-3 py-2" data-testid="agent-versions-footer">
        <p className="min-w-0 truncate text-xs text-muted-foreground">v{selected.version} selected</p>
        <div className="flex flex-wrap items-center gap-1">
          {!selected.current && selected.version !== newest && (
            <Button variant="ghost" size="sm" onClick={() => setRestoreTarget(selected)}>
              <RotateCcw /> Restore
            </Button>
          )}
          <Button variant="ghost" size="sm" asChild data-testid="agent-compare-link">
            <Link href={`/build/agents/${agentId}/versions/compare`}>
              <GitCompare /> Compare
            </Link>
          </Button>
          {publishable && (
            <Button size="sm" onClick={onPublish} data-testid="versions-publish">
              <Rocket /> Publish
            </Button>
          )}
        </div>
      </div>
      <RestoreVersionDialog
        target={restoreTarget}
        newest={newest}
        noun="agent"
        restoring={restoring}
        restoreConsequence="Workflows keep the version they were published with until they are republished."
        onClose={() => setRestoreTarget(null)}
        onRestore={onRestore}
      />
    </div>
  );
}
