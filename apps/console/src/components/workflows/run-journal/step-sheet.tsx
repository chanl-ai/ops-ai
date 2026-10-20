'use client';

import { DetailSheet, type DetailSheetNavigation } from '@/components/shared/detail-sheet';
import { JsonBlock } from '@/components/shared/json-block';
import { KeyValues, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { relativeTime } from '@/lib/format';
import type { EngineRunStep } from '@/lib/types/engine';

import { RunStatus } from './run-status';

/** One step of a run: what went in, what came out and through which port, its error, and every attempt. */
export function StepSheet({ step, nodeName, onOpenChange, navigation }: { step: EngineRunStep | null; nodeName: (id: string) => string; onOpenChange: (open: boolean) => void; navigation?: DetailSheetNavigation }) {
  if (!step) return <DetailSheet open={false} onOpenChange={onOpenChange} title="">{null}</DetailSheet>;
  return (
    <DetailSheet
      open
      onOpenChange={onOpenChange}
      title={nodeName(step.nodeId)}
      description={<span className="font-mono text-xs">{step.nodeId}{step.iteration ? ` · iteration ${step.iteration}` : ''}</span>}
      tags={<RunStatus status={step.status} />}
      navigation={navigation}
      scrollKey={`${step.nodeId}-${step.iteration}`}
      testId="run-step-sheet"
    >
      <div className="flex flex-col gap-4">
        {step.error && (
          <Alert variant="destructive">
            <AlertTitle>The step failed</AlertTitle>
            <AlertDescription>{step.error}</AlertDescription>
          </Alert>
        )}
        <KeyValues rows={[['Port taken', step.port ?? '—'], ['Attempts', String(step.attempts.length)]]} />
        <Section title="Input">
          <JsonBlock value={step.input ?? null} wrap />
        </Section>
        <Section title="Output">
          <JsonBlock value={step.output ?? null} wrap />
        </Section>
        <Section title="Attempts" description="Each try with its idempotency key; a write gets one attempt." flush>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Port</TableHead>
                <TableHead>Key</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {step.attempts.map((a) => (
                <TableRow key={a.attempt} data-testid="run-step-attempt">
                  <TableCell className="tabular-nums">{a.attempt}</TableCell>
                  <TableCell>
                    <RunStatus status={a.status} />
                  </TableCell>
                  <TableCell className="font-mono text-xs">{a.port ?? '—'}</TableCell>
                  <TableCell className="max-w-48 truncate font-mono text-xs" title={a.key}>
                    {a.key}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{relativeTime(a.startedAt)}</TableCell>
                  <TableCell className="max-w-48 truncate text-xs text-destructive" title={a.error ?? undefined}>
                    {a.error ?? ''}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Section>
      </div>
    </DetailSheet>
  );
}
