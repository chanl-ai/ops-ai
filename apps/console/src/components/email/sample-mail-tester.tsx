'use client';

import * as React from 'react';
import { FlaskConical, ShieldCheck } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { SettingsSection } from '@/components/shared/settings-section';
import { ConfidenceBar, PriorityBadge } from '@/components/status-badges';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { SampleMailInput, SampleMailResult } from '@/lib/types/cases';

const SAMPLES: (SampleMailInput & { label: string })[] = [
  { label: 'Disputed charge', from: 'customer@example.com', subject: 'Charge I did not make', body: 'There is a charge of $412.18 from TRVL*BOOKINGS on my Visa ending 4471 dated 2026-09-28. I did not make it. Please reverse it.' },
  { label: 'Stolen card', from: 'customer@example.com', subject: 'Wallet stolen', body: 'My wallet was stolen this morning with my card ending 7720 in it. Please block the card.' },
  { label: 'Unclear request', from: 'customer@example.com', subject: 'Question', body: 'Hi, can someone call me back about my account? Thanks.' },
];

/**
 * Runs a sample email through the draft configuration (not the live one), so routing and approval changes
 * can be checked before a publish request.
 */
export function SampleMailTester({ onRun, isPending }: { onRun: (input: SampleMailInput) => Promise<SampleMailResult>; isPending: boolean }) {
  const [input, setInput] = React.useState<SampleMailInput>({ from: '', subject: '', body: '' });
  const [result, setResult] = React.useState<SampleMailResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const run = async () => {
    if (!input.body.trim()) return setError('Paste or write an email body first.');
    setError(null);
    try {
      setResult(await onRun(input));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <SettingsSection title="Try a sample email" description="Classifies, extracts and routes against this draft. Nothing is sent and no case opens.">
      <div className="grid gap-4 lg:grid-cols-2" data-testid="sample-mail">
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            {SAMPLES.map((s) => (
              <Button key={s.label} variant="outline" size="sm" onClick={() => {
                  setInput({ from: s.from, subject: s.subject, body: s.body });
                  setResult(null);
                }}>
                {s.label}
              </Button>
            ))}
          </div>
          <FormField id="sample-subject" label="Subject">
            <Input id="sample-subject" value={input.subject} onChange={(e) => setInput({ ...input, subject: e.target.value })} placeholder="e.g. Charge I did not make" />
          </FormField>
          <FormField id="sample-body" label="Body" error={error ?? undefined}>
            <Textarea id="sample-body" rows={6} value={input.body} onChange={(e) => setInput({ ...input, body: e.target.value })} placeholder="e.g. There is a charge of $412 on my card ending 4471…" aria-invalid={!!error} />
          </FormField>
          <LoadingButton isLoading={isPending} onClick={run} className="self-start">
            <FlaskConical className="size-4" /> Run sample
          </LoadingButton>
        </div>

        <div className="rounded-lg border bg-card p-4 text-sm" aria-live="polite">
          {!result ? (
            <p className="text-muted-foreground">The result shows the intent, the fields pulled out, the queue and SLA, and which actions would wait for approval.</p>
          ) : (
            <div className="flex flex-col gap-3" data-testid="sample-result">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{result.intentName}</span>
                <ConfidenceBar value={result.confidence} />
              </div>
              {result.belowThreshold && (
                <Alert>
                  <AlertDescription>Below the confidence threshold, so it goes to {result.queue} for a person to sort.</AlertDescription>
                </Alert>
              )}
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span>Queue: <span className="text-foreground">{result.queue}</span></span>·<PriorityBadge priority={result.priority} />·<span>SLA {result.slaHours} h</span>
              </div>
              {result.fields.length > 0 && (
                <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
                  {result.fields.map((f) => (
                    <React.Fragment key={f.key}>
                      <dt className="text-muted-foreground">{f.label}</dt>
                      <dd className={f.value ? '' : 'text-amber-700 dark:text-amber-400'}>{f.value ?? 'Not found in the email'}</dd>
                    </React.Fragment>
                  ))}
                </dl>
              )}
              {result.actions.length > 0 && (
                <div className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-muted-foreground">Would draft</span>
                  {result.actions.map((a) => (
                    <div key={a.label} className="flex items-center justify-between gap-2 text-xs">
                      <span>{a.label}</span>
                      <span className="flex items-center gap-1 text-muted-foreground">
                        {a.needsApproval && <ShieldCheck className="size-3.5" />}
                        {a.needsApproval ? `${a.approverGroup}${a.fourEyes ? ' · two approvers' : ''}` : 'Runs on its own'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted-foreground">Took {result.tookMs} ms</p>
            </div>
          )}
        </div>
      </div>
    </SettingsSection>
  );
}
