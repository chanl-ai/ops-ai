'use client';

import * as React from 'react';
import { Check, Sparkles } from 'lucide-react';

import { PromptDiff } from '@/components/prompts/prompt-diff';
import { DialogShell } from '@/components/shared/dialog-shell';
import { QueryError } from '@/components/shared/query-states';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { useDraftBrief } from '@/hooks/queries';
import type { AgentBrief } from '@/lib/types/domain';
import type { BriefDraft } from '@/lib/types/references';

// The headings a draft proposes, in the brief card's order; lists are shown one rule per line.
const HEADINGS = [
  { key: 'purpose', label: 'Job', from: (d: BriefDraft) => d.job },
  { key: 'howToAnswer', label: 'How to answer', from: (d: BriefDraft) => d.howToAnswer },
  { key: 'handOff', label: 'Hand off when', from: (d: BriefDraft) => d.handOff },
  { key: 'examples', label: 'Examples', from: (d: BriefDraft) => d.examples },
  { key: 'never', label: 'Never', from: (d: BriefDraft) => d.never },
] as const;
type Key = (typeof HEADINGS)[number]['key'];
const asText = (v: string | string[]) => (Array.isArray(v) ? v.join('\n') : v);

/**
 * Draft on the brief card: the builder describes the job, the agent's model proposes a text per heading, and each
 * heading shows as a change against the current brief to accept or skip. Accepting is an ordinary edit of the brief,
 * so it autosaves to the draft like typing; skipping or closing keeps the brief as it was.
 */
export function DraftBriefDialog({ agentId, brief, onBrief, open, onOpenChange }: { agentId: string; brief: AgentBrief; onBrief: (next: AgentBrief) => void; open: boolean; onOpenChange: (open: boolean) => void }) {
  const draft = useDraftBrief(agentId);
  const [description, setDescription] = React.useState('');
  const [decided, setDecided] = React.useState<Partial<Record<Key, 'accepted' | 'skipped'>>>({});
  const proposal = draft.data;
  // Only headings whose proposal differs from what the brief already says.
  const changes = proposal ? HEADINGS.filter((h) => { const next = asText(h.from(proposal)); return next.trim() !== '' && next !== asText(brief[h.key]); }) : [];
  const open_ = changes.filter((h) => !decided[h.key]);

  const reset = () => {
    draft.reset();
    setDecided({});
  };
  const accept = (keys: Key[]) => {
    if (!proposal) return;
    const next = { ...brief };
    for (const h of HEADINGS) if (keys.includes(h.key)) Object.assign(next, { [h.key]: h.from(proposal) });
    onBrief(next);
    setDecided((d) => ({ ...d, ...Object.fromEntries(keys.map((k) => [k, 'accepted'])) }));
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => {
        if (!o) reset();
        onOpenChange(o);
      }}
      size="lg"
      title="Draft the brief"
      description="Describe the job, or paste a procedure. Each heading comes back as a change you accept or skip; nothing is saved until you accept."
      onSubmit={proposal ? undefined : () => description.trim() && draft.mutate(description.trim())}
      footer={
        proposal ? (
          <>
            <Button variant="outline" onClick={reset}>
              Start over
            </Button>
            {open_.length > 1 ? (
              <Button onClick={() => accept(open_.map((h) => h.key))} data-testid="draft-brief-accept-all">
                Accept all
              </Button>
            ) : (
              <Button onClick={() => onOpenChange(false)}>Done</Button>
            )}
          </>
        ) : (
          <>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={!description.trim() || draft.isPending} data-testid="draft-brief-submit">
              <Sparkles className="size-4" /> {draft.isPending ? 'Drafting…' : 'Draft'}
            </Button>
          </>
        )
      }
    >
      {!proposal ? (
        <div className="flex flex-col gap-2">
          <Label htmlFor="draft-brief-description">What does this agent do?</Label>
          <Textarea id="draft-brief-description" rows={6} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Answers branch staff about where a loan application stands, and hands disputes to a lending officer." data-testid="draft-brief-description" />
          {draft.isError && <QueryError what="the draft" error={draft.error} onRetry={() => draft.mutate(description.trim())} retrying={draft.isPending} />}
        </div>
      ) : !changes.length ? (
        <p className="text-sm text-muted-foreground" data-testid="draft-brief-same">The draft says what the brief already says. Nothing to change.</p>
      ) : (
        <div className="flex flex-col gap-4" data-testid="draft-brief-changes">
          {changes.map((h) => (
            <section key={h.key} className="flex flex-col gap-2" data-testid={`draft-brief-${h.key}`}>
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-medium">{h.label}</h3>
                {decided[h.key] ? (
                  <span className="flex items-center gap-1 text-xs text-muted-foreground">
                    {decided[h.key] === 'accepted' && <Check className="size-3.5" />} {decided[h.key] === 'accepted' ? 'Accepted' : 'Skipped'}
                  </span>
                ) : (
                  <div className="flex gap-1">
                    <Button size="sm" variant="ghost" onClick={() => setDecided((d) => ({ ...d, [h.key]: 'skipped' }))}>
                      Skip
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => accept([h.key])}>
                      Accept
                    </Button>
                  </div>
                )}
              </div>
              <PromptDiff before={asText(brief[h.key])} after={asText(h.from(proposal!))} against={`the current ${h.label}`} />
            </section>
          ))}
        </div>
      )}
    </DialogShell>
  );
}
