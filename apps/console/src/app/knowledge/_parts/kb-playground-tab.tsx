'use client';

import * as React from 'react';
import { Send } from 'lucide-react';

import { QueryResult } from '@/components/knowledge/query-result';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useKbQuery } from '@/hooks/knowledge-queries';
import { count } from '@/lib/format';
import type { KnowledgeBaseDetail, PlaygroundAnswer } from '@/lib/types/knowledge';

interface Turn {
  id: string;
  question: string;
  result?: PlaygroundAnswer;
  error?: string;
}

const emptyResult = (id: string, question: string): PlaygroundAnswer => ({ id, question, matchers: [], answer: '', citations: [], chunks: [], retrievalMs: 0, synthesisMs: 0 });

/**
 * Ask the knowledge base a question as an agent would and see the answer with the passages it cites, by page and
 * section. kb-service answers with the base's own retrieval (keyword search over its indexed chunks); it takes the
 * question alone, so this page offers no search mode, limit or person to run as that it would not use.
 */
export function KbPlaygroundTab({ kb }: { kb: KnowledgeBaseDetail }) {
  const query = useKbQuery(kb.id);
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [input, setInput] = React.useState('');
  const endRef = React.useRef<HTMLDivElement>(null);
  const failed = kb.health === 'failed';

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' });
  }, [turns]);

  async function ask(text: string) {
    const question = text.trim();
    if (!question || failed || query.isPending) return;
    const id = `q_${Date.now()}`;
    setInput('');
    setTurns((ts) => [...ts, { id, question }]);
    try {
      const result = await query.mutateAsync({ question });
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, result } : t)));
    } catch (e) {
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, error: (e as Error).message } : t)));
    }
  }

  return (
    <div className="flex min-h-[60vh] min-w-0 flex-col gap-3">
      {kb.indexing && (
        <Alert>
          <AlertDescription>
            The index is refreshing ({count(kb.indexing.done)} of {count(kb.indexing.total)}); results may be partial.
          </AlertDescription>
        </Alert>
      )}
      {failed && (
        <Alert variant="destructive">
          <AlertDescription>The last refresh failed, so questions are disabled until the index is rebuilt. See why on the Overview tab.</AlertDescription>
        </Alert>
      )}
      <div className="flex flex-1 flex-col gap-4">
        {turns.length === 0 && kb.suggestedQuestions.length > 0 && (
          <div className="rounded-lg border border-dashed p-6">
            <p className="mb-3 text-sm font-medium">Try a question agents ask this knowledge base</p>
            <div className="flex flex-wrap gap-2">
              {kb.suggestedQuestions.map((q) => (
                <Button key={q} variant="outline" size="sm" disabled={failed} onClick={() => ask(q)} className="rounded-full font-normal">
                  {q}
                </Button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t) =>
          t.result || t.error ? (
            <QueryResult key={t.id} result={t.result ?? emptyResult(t.id, t.question)} settings={kb.retrieval} kbId={kb.id} error={t.error} onRetry={() => (setTurns((ts) => ts.filter((x) => x.id !== t.id)), ask(t.question))} />
          ) : (
            <div key={t.id} className="rounded-lg border bg-card px-4 py-3 text-sm">
              <p className="font-medium">{t.question}</p>
              <p className="mt-1 animate-pulse text-xs text-muted-foreground">Searching {kb.name}…</p>
            </div>
          ),
        )}
        <div ref={endRef} />
      </div>
      <div className="sticky bottom-0 rounded-lg border bg-background p-2 shadow-sm">
        <div className="flex items-end gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void ask(input);
              }
            }}
            placeholder={failed ? 'Questions are disabled while the last refresh is failed' : 'Ask a question…'}
            aria-label="Question"
            disabled={failed}
            rows={2}
            className="min-h-11 resize-none border-0 shadow-none focus-visible:ring-0"
          />
          <Button size="icon" onClick={() => void ask(input)} disabled={!input.trim() || failed || query.isPending} aria-label="Send">
            <Send className="size-4" />
          </Button>
        </div>
        <p className="px-1 pt-1 text-[11px] text-muted-foreground">Enter to send · Shift+Enter for a new line</p>
      </div>
    </div>
  );
}
