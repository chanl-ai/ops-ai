'use client';

import { notFound } from 'next/navigation';
import { Sparkles } from 'lucide-react';

import { KindEmpty, KindError, KindLoading, KindView, type KindViewProps } from '@/components/chat/widgets/kind-view';
import { PageLayout } from '@/components/page-layout';
import { Badge } from '@/components/ui/badge';
import samples from '@/lib/widgets/kind-samples.json';

// What each kind is for, and the words its empty and error states use; the industry stays in the samples.
const KINDS: Record<string, { name: string; empty: string; error: string }> = {
  metric: { name: 'Stat with trend', empty: 'No figure for this period yet.', error: 'The figure could not load.' },
  table: { name: 'Table', empty: 'No rows match.', error: 'The table could not load.' },
  chart: { name: 'Chart', empty: 'Nothing to chart for this period.', error: 'The chart could not load.' },
  timeline: { name: 'Timeline', empty: 'No activity yet.', error: 'The activity could not load.' },
  tracker: { name: 'Status tracker', empty: 'This process has not started.', error: 'The status could not load.' },
  entity: { name: 'Entity card', empty: 'Nothing found for that name or number.', error: 'The record could not load.' },
  comparison: { name: 'Comparison', empty: 'Nothing to compare yet.', error: 'The comparison could not load.' },
  checklist: { name: 'Checklist', empty: 'Nothing left to do.', error: 'The checklist could not load.' },
  form: { name: 'Form', empty: 'This form has no fields.', error: 'The form could not load.' },
  confirm: { name: 'Confirmation', empty: 'Nothing waits for an answer.', error: 'The question could not load.' },
  document: { name: 'Document preview', empty: 'The cited page has no text.', error: 'The file could not be opened.' },
  quote: { name: 'Quote', empty: 'This answer cites nothing.', error: 'The source could not load.' },
  plan: { name: 'Plan', empty: 'The agent has no plan for this yet.', error: 'The plan could not load.' },
  reasoning: { name: 'Chain of thought', empty: 'The agent answered without searching or calling tools.', error: 'The steps could not load.' },
  slots: { name: 'Appointment picker', empty: 'No times are open this week.', error: 'Open times could not load.' },
  receipt: { name: 'Receipt or invoice', empty: 'This invoice has no lines.', error: 'The invoice could not load.' },
  contact: { name: 'Contact card', empty: 'No contact on file.', error: 'The contact could not load.' },
};

/**
 * The c-176 gallery: every widget kind an agent can emit, each with samples from two industries, drawn by the same
 * renderer the chat uses (components/chat/widgets/kind-view.tsx), then its loading, empty and error states. Samples are
 * lib/widgets/kind-samples.json, which the kernel's tests check against each kind's schema. Dev server only.
 */
export default function WidgetsPolishPreview() {
  if (process.env.NODE_ENV !== 'development') notFound();
  const all = samples as Record<string, { industry: string; data: Record<string, unknown> }[]>;
  return (
    <PageLayout icon={Sparkles} title="Chat widgets (c-176)" description="Every kind an agent can show, in two industries each, then its loading, empty and error states.">
      <div className="flex flex-col gap-10">
        {Object.entries(KINDS).map(([kind, meta]) => (
          <section key={kind} data-screen={kind} className="flex flex-col gap-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <h2 className="text-base font-semibold">{meta.name}</h2>
              <code className="font-mono text-xs text-muted-foreground">kind: {kind}</code>
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              {(all[kind] ?? []).map((s) => (
                <div key={s.industry} className="flex min-w-0 flex-col gap-1.5">
                  <Badge variant="secondary" className="w-fit">
                    {s.industry}
                  </Badge>
                  <KindView node={{ type: kind, ...s.data } as KindViewProps['node']} actions={{ onReply: () => undefined }} onOpenFile={() => undefined} />
                </div>
              ))}
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <KindLoading label={`Loading ${meta.name.toLowerCase()}`} />
              <KindEmpty text={meta.empty} />
              <KindError text={meta.error} onRetry={() => undefined} />
            </div>
          </section>
        ))}
      </div>
    </PageLayout>
  );
}
