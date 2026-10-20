'use client';

import { BookOpen, Gauge, ShieldCheck, Sparkles, UserCheck, Wrench } from 'lucide-react';

import { ChainOfThought, ChainOfThoughtContent, ChainOfThoughtHeader, ChainOfThoughtStep } from '@/components/ai-elements/chain-of-thought';
import type { ApprovalWidget, ChatMessage } from '@/lib/types/chat';

const CALL_STATE: Record<string, { label: string; className: string }> = {
  success: { label: 'done', className: 'text-success-text' },
  failed: { label: 'failed', className: 'text-destructive' },
  running: { label: 'still running', className: 'text-muted-foreground' },
};

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`;

/** A tool the agent's draft holds, and the approval a call of it waits for (null when none). */
export interface HeldTool {
  name: string;
  approval: string | null;
}

/**
 * Why a test reply answered as it did (c-170, read from the stored reply since c-285): the knowledge it searched and
 * cited, the tools it called and how each went, where it paused for a review, the skills it loaded and a guardrail that
 * fired, and what the reply spent (c-286). Each step says so when there was nothing, so a plain reply still shows that
 * nothing was searched or called.
 */
export function TestWhy({ message, kbNames, held }: { message: ChatMessage; kbNames: Record<string, string>; held: HeldTool[] }) {
  const citations = message.citations ?? [];
  const calls = message.toolCalls ?? [];
  const skills = message.skills ?? [];
  const searched = message.settings?.knowledgeBaseIds ?? [];
  const pause = (message.widgets ?? []).find((w): w is ApprovalWidget => w.kind === 'approval');
  const gated = calls.find((c) => c.gated);
  const fired = message.guardrail;
  const spent = message.usage;
  const pausing = held.filter((t) => t.approval);
  return (
    <ChainOfThought defaultOpen className="rounded-md border bg-muted/30 p-2" data-testid="test-steps">
      <ChainOfThoughtHeader>What the agent did</ChainOfThoughtHeader>
      <ChainOfThoughtContent>
        <ChainOfThoughtStep
          icon={BookOpen}
          status="complete"
          label={citations.length ? `Cited ${plural(citations.length, 'passage')}` : searched.length ? 'Searched its knowledge, cited nothing' : 'No knowledge bases to search'}
          description={searched.length ? `Searched ${searched.map((id) => kbNames[id] ?? id).join(', ')}` : 'Add knowledge bases on the agent to ground its answers.'}
          data-testid="test-step-knowledge"
        >
          {citations.map((c) => (
            <div key={c.n} className="flex flex-col gap-0.5 rounded-md border bg-background px-2 py-1.5">
              <span className="font-medium">
                {c.title}
                {c.section ? ` · ${c.section}` : ''}
                {c.page ? ` · page ${c.page}` : ''}
              </span>
              {c.snippet && <q className="text-muted-foreground italic">{c.snippet}</q>}
            </div>
          ))}
        </ChainOfThoughtStep>
        <ChainOfThoughtStep
          icon={Wrench}
          status="complete"
          label={calls.length ? `Called ${plural(calls.length, 'tool')}` : 'Called no tools'}
          description={held.length ? `Holds ${held.map((t) => t.name).join(', ')}` : 'Holds no tools'}
          data-testid="test-step-tools"
        >
          {calls.map((c) => {
            const state = c.gated ? { label: 'stopped for a review', className: 'text-warning-text' } : (CALL_STATE[c.status] ?? CALL_STATE.running);
            return (
              <div key={c.id} className="flex flex-wrap items-baseline gap-x-2 rounded-md border bg-background px-2 py-1.5">
                <span className="font-mono">{c.name}</span>
                <span className={state.className}>{state.label}</span>
                {c.durationMs > 0 && <span className="text-muted-foreground">{c.durationMs} ms</span>}
              </div>
            );
          })}
        </ChainOfThoughtStep>
        <ChainOfThoughtStep
          icon={UserCheck}
          status={pause || gated ? 'active' : 'complete'}
          label={pause || gated ? 'Paused for a review' : pausing.length ? 'Did not pause this time' : 'Nothing it holds pauses for a review'}
          description={!pause && !gated && pausing.length ? `These pause when called: ${pausing.map((t) => `${t.name} (${t.approval})`).join('; ')}` : undefined}
          data-testid="test-step-pause"
        >
          {pause ? (
            <span className="text-warning-text" data-testid="test-would-pause">
              Waiting on {pause.waitingOn ?? 'a reviewer'}: {pause.title}
              {pause.stepUp && ', and deciding it needs a step-up sign-in'}.
            </span>
          ) : gated?.gated ? (
            <span className="text-warning-text" data-testid="test-would-pause">
              {gated.gated.gate} for {gated.gated.reviewers}.
            </span>
          ) : null}
        </ChainOfThoughtStep>
        <ChainOfThoughtStep icon={Sparkles} status="complete" label={skills.length ? `Loaded ${plural(skills.length, 'skill')}` : 'Loaded no skills'} data-testid="test-step-skills">
          {skills.map((s) => (
            <span key={s.skillId}>
              Loaded skill <span className="font-medium">{s.name}</span> <span className="font-mono">v{s.version}</span>
              {s.matched && <span className="text-muted-foreground"> · {s.matched}</span>}
            </span>
          ))}
        </ChainOfThoughtStep>
        <ChainOfThoughtStep
          icon={Gauge}
          status="complete"
          label={spent ? `${message.model ?? 'Model'} · ${plural(spent.inputTokens + spent.outputTokens, 'token')} · ${spent.cost}` : 'No model call recorded'}
          description={spent ? `${plural(spent.calls, 'model call')}${spent.seconds != null ? ` · ${spent.seconds} s` : ''}` : undefined}
          data-testid="test-step-spent"
        />
        <ChainOfThoughtStep
          icon={ShieldCheck}
          status={fired ? 'active' : 'complete'}
          label={fired ? `${{ before: 'Not answered', after: 'Answer withdrawn', corrected: 'Answer rewritten' }[fired.when]} by ${fired.name} v${fired.version}` : 'No guardrail fired'}
          description={fired ? `It blocks “${fired.topic}”.` : undefined}
          data-testid="test-step-guardrail"
        />
      </ChainOfThoughtContent>
    </ChainOfThought>
  );
}
