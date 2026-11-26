'use client';

import * as React from 'react';
import { AlertTriangle, CheckCircle2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import type { DefinitionValidation } from '@/lib/types/engine';
import { cn } from '@/lib/utils';

import { ChecksPanel } from './checks-panel';

/**
 * The working copy's problems in the page header, beside its save state: a count that opens the list, each line
 * naming its step and opening that step's settings. An error stops a publish; a warning never does. On a phone it shows
 * only when there is something to read; "No problems" moves into the header's menu (LifecycleActions).
 */
export function ProblemsChip({
  validation,
  checking,
  failed,
  nodeName,
  onSelectNode,
}: {
  validation: DefinitionValidation | null;
  checking: boolean;
  failed: string | null;
  nodeName: (id: string) => string;
  onSelectNode: (id: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const checks = validation?.checks ?? [];
  const errors = checks.filter((c) => c.level === 'error').length;
  const warnings = checks.filter((c) => c.level === 'warning').length;
  const label = checking ? 'Checking…' : errors ? `${errors} ${errors === 1 ? 'problem' : 'problems'}` : warnings ? `${warnings} ${warnings === 1 ? 'warning' : 'warnings'}` : 'No problems';
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm" className={cn(errors > 0 && 'border-destructive text-destructive-text', !errors && !warnings && !checking && 'max-sm:hidden')} data-testid="definition-problems" data-errors={errors}>
          {errors > 0 ? <AlertTriangle /> : warnings > 0 ? <AlertTriangle className="text-warning-text" /> : <CheckCircle2 className="text-success-text" />}
          <span className="tabular-nums">{label}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 max-w-[calc(100vw-2rem)] p-0">
        <ChecksPanel
          validation={validation}
          checking={checking}
          failed={failed}
          nodeName={nodeName}
          onSelectNode={(id) => {
            setOpen(false);
            onSelectNode(id);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
