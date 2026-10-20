'use client';

import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';

import { Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { plural } from '@/lib/format';
import type { DefinitionCheck, DefinitionValidation } from '@/lib/types/engine';
import { cn } from '@/lib/utils';

function CheckLine({ check, nodeName }: { check: DefinitionCheck; nodeName: (id: string) => string }) {
  const isError = check.level === 'error';
  const Icon = isError || check.level === 'warning' ? AlertTriangle : Info;
  return (
    <>
      <Icon className={cn('mt-0.5 size-4 shrink-0', isError ? 'text-destructive' : check.level === 'warning' ? 'text-warning-text' : 'text-muted-foreground')} />
      <span className="min-w-0 flex-1 text-left">
        <span className="block text-sm break-words">{check.message}</span>
        <span className="block truncate text-xs text-muted-foreground">{check.node ? nodeName(check.node) : 'Whole workflow'}</span>
      </span>
      <Badge variant={isError ? 'destructive' : 'outline'} className="shrink-0">
        {check.level}
      </Badge>
    </>
  );
}

/** The server's checks for the definition on screen, and nothing else: the console runs no checks of its own. */
export function ChecksPanel({
  validation,
  checking,
  failed,
  nodeName,
  onSelectNode,
}: {
  validation: DefinitionValidation | null;
  checking: boolean;
  /** The last validate request failed, so the checks shown may be stale. */
  failed: string | null;
  nodeName: (id: string) => string;
  onSelectNode: (id: string) => void;
}) {
  const checks = validation?.checks ?? [];
  const errors = checks.filter((c) => c.level === 'error').length;
  const summary = checking || !validation ? 'Checking…' : checks.length === 0 ? 'No problems' : `${plural(checks.length, 'check')}${errors ? `, ${plural(errors, 'error')}` : ''}`;
  return (
    <div data-testid="definition-checks" className="min-w-0">
      <Section title="Checks" description={summary} flush>
        {failed && <p className="border-b px-4 py-2.5 text-sm text-destructive">Couldn’t check this workflow: {failed}</p>}
        {validation && checks.length === 0 ? (
          <p className="flex items-center gap-2 px-4 py-3 text-sm text-success-text">
            <CheckCircle2 className="size-4" /> No problems
          </p>
        ) : (
          <div className="flex flex-col divide-y">
            {checks.map((c, i) => {
              const node = c.node;
              return (
                <div key={`${c.code}-${node ?? ''}-${i}`} data-testid="definition-check" data-level={c.level} data-node={node ?? undefined} className="min-w-0">
                  {node ? (
                    <Button type="button" variant="ghost" onClick={() => onSelectNode(node)} className="h-auto w-full items-start justify-start gap-2 rounded-none px-4 py-2.5 font-normal whitespace-normal">
                      <CheckLine check={c} nodeName={nodeName} />
                    </Button>
                  ) : (
                    <div className="flex items-start gap-2 px-4 py-2.5">
                      <CheckLine check={c} nodeName={nodeName} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Section>
    </div>
  );
}
