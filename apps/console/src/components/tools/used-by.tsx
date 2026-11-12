'use client';

import Link from 'next/link';
import { Bot, Route } from 'lucide-react';

import { QueryError } from '@/components/shared/query-states';
import { Section } from '@/components/shared/surface';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { plural } from '@/lib/format';
import type { ToolRow } from '@/lib/types/tool-directory';

/** Where a tool's row opens: an app's or custom tool's own page, a workflow's, or an agent's. */
export function toolHref(t: ToolRow): string | null {
  if (t.moduleId) return `/data/tools/${encodeURIComponent(t.moduleId)}/operations/${encodeURIComponent(t.name)}`;
  if (t.kind === 'workflow') return `/build/workflows/definitions/${encodeURIComponent(t.id.replace(/^workflow:/, ''))}`;
  if (t.kind === 'agent') return `/build/agents/${encodeURIComponent(t.id.replace(/^agent:/, ''))}`;
  return null;
}

/** Who uses a tool: the agents granted it and the workflows with a step that calls it, each opening its page. */
export function UsedByList({ usedBy }: { usedBy: ToolRow['usedBy'] }) {
  return (
    <ul className="flex flex-col gap-1" data-testid="used-by-list">
      {usedBy.agents.map((a) => (
        <li key={`a-${a.id}`}>
          <Link href={`/build/agents/${encodeURIComponent(a.id)}`} className="inline-flex items-center gap-1.5 text-sm underline-offset-4 hover:underline">
            <Bot className="size-3.5 text-muted-foreground" /> {a.name}
          </Link>
        </li>
      ))}
      {usedBy.workflows.map((w) => (
        <li key={`w-${w.id}`}>
          <Link href={`/build/workflows/definitions/${encodeURIComponent(w.id)}`} className="inline-flex items-center gap-1.5 text-sm underline-offset-4 hover:underline">
            <Route className="size-3.5 text-muted-foreground" /> {w.name}
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** A list cell: the first user and how many more, opening the full list; "Not used yet" when nothing uses the tool. */
export function UsedByCell({ usedBy, testId }: { usedBy: ToolRow['usedBy']; testId?: string }) {
  const all = [...usedBy.agents, ...usedBy.workflows];
  if (!all.length)
    return (
      <span className="text-xs text-muted-foreground" data-testid={testId}>
        Not used yet
      </span>
    );
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-auto max-w-48 justify-start px-1.5 py-0.5 font-normal" data-testid={testId}>
          <span className="truncate">{all[0].name}</span>
          {all.length > 1 && <span className="text-muted-foreground">+{all.length - 1}</span>}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64">
        <p className="mb-2 text-xs text-muted-foreground">
          {[usedBy.agents.length ? plural(usedBy.agents.length, 'agent') : '', usedBy.workflows.length ? plural(usedBy.workflows.length, 'workflow') : ''].filter(Boolean).join(' and ')}
        </p>
        <UsedByList usedBy={usedBy} />
      </PopoverContent>
    </Popover>
  );
}

/** A tool page's Used by: the agents and workflows that use the tool, or that nothing does yet. */
export function UsedBySection({ row }: { row: { data?: ToolRow; isPending: boolean; isError: boolean; error: unknown; refetch: () => unknown; isFetching: boolean } }) {
  return (
    <Section title="Used by" description="The agents granted this tool and the workflows with a step that calls it." id="tool-used-by">
      {row.isPending ? (
        <Skeleton className="h-10 w-full" />
      ) : row.isError || !row.data ? (
        <QueryError what="who uses this tool" error={row.error as Error} onRetry={() => void row.refetch()} retrying={row.isFetching} />
      ) : row.data.usedBy.agents.length + row.data.usedBy.workflows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Not used yet. Grant it to an agent, or add it as a step in a workflow.</p>
      ) : (
        <UsedByList usedBy={row.data.usedBy} />
      )}
    </Section>
  );
}
