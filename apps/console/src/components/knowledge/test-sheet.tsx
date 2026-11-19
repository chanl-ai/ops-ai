'use client';

import * as React from 'react';
import Link from 'next/link';
import { Bot, Copy, FileText, FlaskConical, Send } from 'lucide-react';
import { toast } from 'sonner';

import { SearchTrace } from '@/components/knowledge/search-trace';
import { Row, Rows, Section } from '@/components/shared/surface';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
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
const ALL = 'all';

/**
 * Test a knowledge base from any of its tabs: ask a question, optionally narrowed to one collection, and see the pieces
 * the search used with their scores, the search trace, and an agent's answer. The search comes from kb-service's query
 * route; the answer from one kernel turn of an agent citing this base, so what is shown is what that agent would say.
 * With nothing found, the base's own no-answer message is shown. Nothing is saved.
 */
export function TestSheet({ kb, open, onOpenChange }: { kb: KnowledgeBaseDetail; open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 sm:max-w-2xl" data-testid="kb-test-sheet">
        <SheetHeader className="border-b">
          <SheetTitle className="flex items-center gap-2">
            <FlaskConical className="size-4" /> Test {kb.name}
          </SheetTitle>
          <SheetDescription>Searches the index the same way an agent would. Nothing is saved.</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">{open && <TestPanel kb={kb} />}</div>
      </SheetContent>
    </Sheet>
  );
}

function TestPanel({ kb }: { kb: KnowledgeBaseDetail }) {
  const query = useKbQuery(kb.id);
  const turn = useAgentTurn();
  // A test turn is an agent edit at agents-service (Builder or Admin); anyone else sees the search only.
  const canTest = useCanBuild('agents');
  const agents = useAgentsCiting(kb.id, canTest);
  const [agentId, setAgentId] = React.useState<string>(NO_AGENT);
  const [collection, setCollection] = React.useState<string>(ALL);
  // The base's scope, or with none, the collections its sources write, both on its detail.
  const collections = kb.collections.length ? kb.collections : [...new Set(kb.attached.map((a) => a.source.collection).filter(Boolean))].sort();
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [input, setInput] = React.useState('');
  const endRef = React.useRef<HTMLDivElement>(null);
  const citing = canTest ? (agents.data ?? []) : [];
  React.useEffect(() => {
    if (agentId === NO_AGENT && citing.length) setAgentId(citing[0].id);
  }, [citing, agentId]);
  React.useEffect(() => {
    // From the second question on, the newest answer scrolls into view; the first leaves the form in sight.
    if (turns.length > 1) endRef.current?.scrollIntoView({ block: 'end' });
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
    query.mutate({ question, ...(collection !== ALL ? { collection } : {}) }, { onSuccess: (search) => patch(id, { search }), onError: (e) => patch(id, { searchError: e.message }) });
    if (agent) turn.mutate({ agentId: agent.id, message: question }, { onSuccess: (answer) => patch(id, { answer }), onError: (e) => patch(id, { answerError: e.message }) });
  }

  return (
    <div className="flex min-w-0 flex-col gap-4" data-testid="kb-playground">
      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          ask(input);
        }}
      >
        <div className="flex flex-col gap-1">
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
        <div className="flex flex-col gap-1">
          <label htmlFor="pg-collection" className="text-xs text-muted-foreground">
            Collection
          </label>
          <Select value={collection} onValueChange={setCollection}>
            <SelectTrigger id="pg-collection" className="w-56" data-testid="pg-collection">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All collections</SelectItem>
              {collections.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
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
          {t.searchError ? (
            <Alert variant="destructive">
              <AlertDescription>The search failed: {t.searchError}</AlertDescription>
            </Alert>
          ) : !t.search ? (
            <p className="animate-pulse text-sm text-muted-foreground">Searching {kb.name}…</p>
          ) : (
            <>
              {t.search.noAnswer && (
                <Section title="Answer" description="Nothing passed the base’s floors, so it says its no-answer message">
                  <p className="text-sm" data-testid="pg-no-answer">
                    {t.search.answer}
                  </p>
                </Section>
              )}
              <PiecesUsed result={t.search} />
              <Section title="Search trace" description="What the search did, before any agent reads it" flush>
                <div className="p-3">
                  <SearchTrace result={t.search} settings={kb.retrieval} />
                </div>
              </Section>
            </>
          )}
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

/**
 * The pieces the search returned, best first, each with its document, place and score; Copy as JSON gives them all. The
 * score shown is the piece's best lane score (0 to 1), since the fused rank score is only for ordering.
 */
function PiecesUsed({ result }: { result: PlaygroundAnswer }) {
  const pieces = result.chunks ?? [];
  const best = (n: number, fallback: number) => {
    const lanes = Object.values(result.passages?.[n]?.lanes ?? {});
    return lanes.length ? Math.max(...lanes) : fallback;
  };
  const lanes = result.lanes?.ran.length ? ` · ${result.lanes.ran.join(' and ')}` : '';
  return (
    <Section
      title="Pieces used"
      description={`${plural(pieces.length, 'piece')}${lanes} · ${ms(result.retrievalMs)}`}
      flush
      actions={
        pieces.length > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void navigator.clipboard.writeText(JSON.stringify(pieces, null, 2)).then(() => toast.success('Copied the pieces as JSON'))}
            data-testid="pg-copy-json"
          >
            <Copy className="size-3.5" /> Copy as JSON
          </Button>
        )
      }
    >
      {pieces.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">No piece passed the floors.</p>
      ) : (
        <Rows testId="pg-pieces">
          {pieces.map((c, n) => (
            <Row
              key={c.chunkId}
              leading={<FileText className="size-4 text-muted-foreground" />}
              title={
                <span>
                  {c.documentTitle} <span className="text-muted-foreground">· {c.version}{c.location ? ` · ${c.location}` : ''}</span>
                </span>
              }
              description={
                <span className="line-clamp-2">
                  “{c.text.slice(0, 220)}
                  {c.text.length > 220 ? '…' : ''}” · {c.sourceName}
                </span>
              }
              trailing={<span className="font-mono text-xs tabular-nums">{best(n, c.score).toFixed(2)}</span>}
            />
          ))}
        </Rows>
      )}
    </Section>
  );
}
