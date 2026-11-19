'use client';

import { TriangleAlert } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { plural } from '@/lib/format';
import type { PublishBlocker, Ref } from '@/lib/types/references';

const HEADING: Record<string, string> = { 'brief.purpose': 'Purpose', 'brief.goal': 'Goal', 'brief.howToAnswer': 'How to answer', 'brief.never': 'Never', 'brief.success': 'Success checks' };

/** Where a problem is, in the words of the page: `Purpose`, or `Never, line 2`. */
export const whereIs = (p: PublishBlocker): string | null => {
  const f = p.position?.field;
  if (!f) return null;
  const name = HEADING[f] ?? f;
  return p.position?.index != null ? `${name}, line ${p.position.index + 1}` : name;
};

/**
 * What stops the newest draft from publishing, one row each. "Go to it" puts the caret on the heading the problem
 * names; a reference the team still offers but the agent lost offers "Add it back".
 */
export function PublishProblems({ problems, onGoTo, onAddBack, adding }: { problems: PublishBlocker[]; onGoTo: (field: string) => void; onAddBack: (ref: Ref) => void; adding?: boolean }) {
  if (!problems.length) return null;
  return (
    <div className="flex flex-col gap-2" data-testid="publish-problems">
      <p className="flex items-center gap-2 text-sm font-medium">
        <TriangleAlert className="size-4 text-warning-text" aria-hidden />
        {plural(problems.length, 'problem')} to fix before this can publish
      </p>
      <ul className="flex flex-col divide-y rounded-md border bg-card">
        {problems.map((p, i) => {
          const where = whereIs(p);
          const at = p.kind === 'missing_reference' && p.id ? p.id.indexOf(':') : -1;
          const token = at > 0 && p.id ? [p.id.slice(0, at), p.id.slice(at + 1)] : null;
          return (
            <li key={`${p.kind}-${p.id}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm" data-testid="publish-problem">
              <span className="min-w-0 flex-1">
                {where && <span className="font-medium">{where}: </span>}
                {p.message}
              </span>
              {token && token.length === 2 && (
                <Button type="button" variant="outline" size="sm" disabled={adding} onClick={() => onAddBack({ kind: token[0] as Ref['kind'], id: token[1] })} data-testid="publish-problem-add-back">
                  Add it back
                </Button>
              )}
              {p.position?.field && (
                <Button type="button" variant="link" size="sm" className="h-auto p-0" onClick={() => onGoTo(p.position!.field)} data-testid="publish-problem-go">
                  Go to it
                </Button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
