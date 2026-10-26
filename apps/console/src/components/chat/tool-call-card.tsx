'use client';

import Link from 'next/link';

import { ChatToolCall, type ChatToolState } from '@/components/shared/chat-blocks';
import { useChatAgents } from '@/hooks/chat-queries';
import { ms } from '@/lib/format';
import type { ToolCall } from '@/lib/types/chat';

const SPECIALIST_PREFIX = 'agent__';

const stateOf = (call: ToolCall): ChatToolState => (call.status === 'running' ? 'running' : call.status === 'failed' ? 'failed' : call.gated ? 'gated' : 'success');

/** A v2 workflow tool answers with the run it started; v1 answers with a thread and has no run page. */
const runIdOf = (call: ToolCall): string | null => {
  if (call.server !== 'workflows' || typeof call.output !== 'object' || call.output === null) return null;
  const runId = (call.output as { runId?: unknown }).runId;
  return typeof runId === 'string' && runId ? runId : null;
};

/** One tool call: collapsed to its name and state, open to show where it ran, its input and its output. */
export function ToolCallCard({ call }: { call: ToolCall }) {
  const runId = runIdOf(call);
  const specialist = call.name.startsWith(SPECIALIST_PREFIX);
  // A specialist call (c-174) is named for the agent asked; the reply carries its name, the chat agents list covers the
  // call while it runs.
  const agents = useChatAgents();
  const asked = specialist
    ? ((call.output as { agentName?: string } | undefined)?.agentName ?? agents.data?.find((a) => a.id === call.name.slice(SPECIALIST_PREFIX.length))?.name ?? 'another agent')
    : undefined;
  const detail = (
    <>
      {call.server}
      {call.status === 'success' && ` · ${ms(call.durationMs)}`}
      {call.gated && ` · Drafted for approval at ${call.gated.gate}. Nothing changes in ${call.server} until ${call.gated.reviewers} approve it.`}
      {runId && (
        <>
          {' · '}
          <Link href={`/workflows/runs/${encodeURIComponent(runId)}`} className="underline-offset-4 hover:underline">
            Open run
          </Link>
        </>
      )}
    </>
  );
  return <ChatToolCall name={asked ? `Asking ${asked}` : (call.label ?? call.name)} state={stateOf(call)} input={call.input} output={call.output} error={call.status === 'failed' ? 'The tool call failed.' : undefined} detail={detail} />;
}
