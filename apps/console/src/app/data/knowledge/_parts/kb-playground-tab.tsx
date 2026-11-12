'use client';

import * as React from 'react';
import Link from 'next/link';
import { Bot, Send } from 'lucide-react';

import { SearchTrace } from '@/components/knowledge/search-trace';
import { Section } from '@/components/shared/surface';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAgentsCiting, useAgentTurn, useKbQuery } from '@/hooks/knowledge-queries';
import { useCanBuild } from '@/hooks/me-queries';
import { ms, plural } from '@/lib/format';
import type { AgentTestTurn } from '@/lib/types/domain';
import type { KnowledgeBaseDetail, PlaygroundAnswer } from '@/lib/types/knowledge';

interface Turn {
  id: string;
  question: string;
  agent?: { id: string; name: string };
  search?: PlaygroundAnswer;
  searchError?: string;
  answer?: AgentTestTurn;
  answerError?: string;
}

const NO_AGENT = 'none';

/**
 * Ask this knowledge base a question. The search comes from kb-service's query route (lanes, each passage's scores and
 * the embedding cost); the answer comes from one kernel turn of an agent citing this base, so what is shown is what that
 * agent would say. With no agent citing the base, only the search is shown.
 */
export function KbPlaygroundTab({ kb }: { kb: KnowledgeBaseDetail }) {
  const query = useKbQuery(kb.id);
  const turn = useAgentTurn();
  const agents = useAgentsCiting(kb.id);
  // A test turn is an agent edit at agents-service (Builder or Admin); anyone else sees the search only.
  const canTest = useCanBuild('agents');
  const [agentId, setAgentId] = React.useState<string>(NO_AGENT);
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [input, setInput] = React.useState('');
  const endRef = React.useRef<HTMLDivElement>(null);
  const citing = canTest ? (agents.data ?? []) : [];
  React.useEffect(() => {
    if (agentId === NO_AGENT && citing.length) setAgentId(citing[0].id);
  }, [citing, agentId]);
  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [turns]);
  const busy = query.isPending || turn.isPending;
  const patch = (id: string, p: Partial<Turn>) => setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...p } : t)));

  function ask(text: string) {
    const question = text.trim();
    if (!question || busy) return;
    const id = `q_${Date.now()}`;
    const agent = citing.find((a) => a.id === agentId);
    setInput('');
    setTurns((ts) => [...ts, { id, question, agent }]);
    query.mutate({ question }, { onSuccess: (search) => patch(id, { search }), onError: (e) => patch(id, { searchError: e.message }) });
    if (agent) turn.mutate({ agentId: agent.id, message: question }, { onSuccess: (answer) => patch(id, { answer }), onError: (e) => patch(id, { answerError: e.message }) });
  }

  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="kb-playground">
      <form
        className="flex flex-wrap items-end gap-2 rounded-lg border bg-card p-3"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <div className="flex min-w-64 flex-1 flex-col gap-1">
          <label htmlFor="pg-question" className="text-xs text-muted-foreground">
            Question
          </label>
          <Input id="pg-question" value={input} onChange={(e) => setInput(e.target.value)} placeholder="e.g. how long do I have to dispute a card charge?" />
        </div>
        {canTest && (
        <div className="flex flex-col gap-1">
          <label htmlFor="pg-agent" className="text-xs text-muted-foreground">
            As agent
          </label>
          <Select value={agentId} onValueChange={setAgentId} disabled={!citing.length}>
            <SelectTrigger id="pg-agent" className="w-56" data-testid="pg-agent">
              <SelectValue placeholder={agents.isPending ? 'Loading agents…' : 'No agent cites it'} />
            </SelectTrigger>
            <SelectContent>
              {citing.map((a) => (
                <SelectItem key={a.id} value={a.id}>
                  {a.name}
                </SelectItem>
              ))}
              {!citing.length && (
                <SelectItem value={NO_AGENT} disabled>
                  No agent cites this base
                </SelectItem>
              )}
            </SelectContent>
          </Select>
        </div>
        )}
        <Button type="submit" disabled={!input.trim() || busy} data-testid="pg-ask">
          <Send className="size-4" /> Ask
        </Button>
      </form>
      {agents.isError && <p className="text-xs text-destructive-text">Couldn’t list the agents citing this base: {agents.error.message}</p>}
      {!canTest && <p className="text-xs text-muted-foreground">An agent’s answer needs a Builder or Admin of this team to run its test turn, so only the search is shown.</p>}
      {canTest && !agents.isPending && !agents.isError && !citing.length && (
        <p className="text-xs text-muted-foreground">
          No agent in this team cites {kb.name}, so only the search is shown. Give an agent this knowledge base on its page under{' '}
          <Link href="/build/agents" className="underline underline-offset-4">
            Agents
          </Link>{' '}
          to see its answer here.
        </p>
      )}

      {turns.length === 0 && kb.suggestedQuestions.length > 0 && (
        <div className="rounded-lg border border-dashed p-6">
          <p className="mb-3 text-sm font-medium">Try a question agents ask this knowledge base</p>
          <div className="flex flex-wrap gap-2">
            {kb.suggestedQuestions.map((q) => (
              <Button key={q} variant="outline" size="sm" onClick={() => ask(q)} className="rounded-full font-normal">
                {q}
              </Button>
            ))}
          </div>
        </div>
      )}

      {turns.map((t) => (
        <div key={t.id} className="flex flex-col gap-3" data-testid="pg-turn">
          <p className="text-sm font-medium">{t.question}</p>
          {t.agent && (
            <Section title={`Answer · from a kernel turn on ${t.agent.name}`} description={t.answer ? `${t.answer.citations.length ? `${plural(t.answer.citations.length, 'citation')} · ` : ''}${ms(t.answer.tookMs)}` : undefined}>
              {t.answerError ? (
                <p className="text-sm text-destructive-text">The agent could not answer: {t.answerError}</p>
              ) : !t.answer ? (
                <p className="animate-pulse text-sm text-muted-foreground">{t.agent.name} is answering…</p>
              ) : (
                <AgentAnswer answer={t.answer} />
              )}
            </Section>
          )}
          <Section title="Search" description="What kb-service found for the question, before any agent reads it">
            {t.searchError ? (
              <Alert variant="destructive">
                <AlertDescription>The search failed: {t.searchError}</AlertDescription>
              </Alert>
            ) : !t.search ? (
              <p className="animate-pulse text-sm text-muted-foreground">Searching {kb.name}…</p>
            ) : (
              <SearchTrace result={t.search} settings={kb.retrieval} />
            )}
          </Section>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}

function AgentAnswer({ answer: a }: { answer: AgentTestTurn }) {
  return (
    <div className="flex flex-col gap-3" data-testid="pg-answer">
      {a.wouldPause && (
        <Alert>
          <AlertDescription>In production this turn would pause at {a.wouldPause.gate} for {a.wouldPause.reviewers}.</AlertDescription>
        </Alert>
      )}
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{a.reply}</p>
      {a.citations.length > 0 && (
        <ol className="flex flex-col gap-1.5 text-xs">
          {a.citations.map((c, i) => (
            <li key={i} className="flex flex-col gap-0.5">
              <span>
                <span className="font-mono">[{i + 1}]</span> {c.source} › {c.section}
                {c.page ? ` · page ${c.page}` : ''}
                {c.kbName ? <span className="text-muted-foreground"> · {c.kbName}</span> : null}
              </span>
              {c.quote && <span className="text-muted-foreground italic">“{c.quote}”</span>}
            </li>
          ))}
        </ol>
      )}
      {a.toolCalls.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <Bot className="size-3.5 text-muted-foreground" />
          {a.toolCalls.map((c, i) => (
            <Badge key={i} variant="outline" className="font-mono text-[11px] font-normal">
              {c.name}
              {c.status && c.status !== 'ok' ? ` · ${c.status}` : ''}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
