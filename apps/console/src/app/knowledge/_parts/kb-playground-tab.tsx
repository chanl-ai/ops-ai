'use client';

import * as React from 'react';
import { RotateCcw, Save, Send, Settings2, Square } from 'lucide-react';
import { toast } from 'sonner';

import { QueryResult } from '@/components/knowledge/query-result';
import { RetrievalForm } from '@/components/knowledge/retrieval-form';
import { PermissionNote } from '@/components/run-as/permission-note';
import { RunAsBar } from '@/components/run-as/run-as-bar';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useExcludeItems, useKbQuery, useUpdateKb } from '@/hooks/knowledge-queries';
import { useLookups } from '@/hooks/queries';
import { useRunAsPrincipals } from '@/hooks/run-as-queries';
import { count } from '@/lib/format';
import type { KnowledgeBaseDetail, PlaygroundAnswer, RetrievalSettings } from '@/lib/types/knowledge';
import { cn } from '@/lib/utils';

import { playgroundDraftKey } from './kb-retrieval-tab';

interface Turn {
  id: string;
  question: string;
  result?: PlaygroundAnswer;
  streamed: string;
  streaming: boolean;
  error?: string;
  settings: RetrievalSettings;
}

/** Ask a question, see the answer and the exact chunks behind it, and tune settings until it is right. */
export function KbPlaygroundTab({ kb }: { kb: KnowledgeBaseDetail }) {
  const query = useKbQuery(kb.id);
  const update = useUpdateKb(kb.id);
  const exclude = useExcludeItems();
  const lookups = useLookups();
  const principals = useRunAsPrincipals();
  // Who questions run as; answers and citations are limited to what that person or role can read.
  const [runAsId, setRunAsId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<RetrievalSettings>(kb.retrieval);
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [input, setInput] = React.useState('');
  const [railOpen, setRailOpen] = React.useState(false);
  // Mount the settings form once: in the side column on wide screens, in the sheet otherwise (duplicate ids otherwise).
  const [wide, setWide] = React.useState(false);
  React.useEffect(() => {
    const mq = window.matchMedia('(min-width: 1280px)');
    const update = () => setWide(mq.matches);
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, []);
  const timer = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const endRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    try {
      const raw = sessionStorage.getItem(playgroundDraftKey(kb.id));
      if (raw) {
        setDraft(JSON.parse(raw));
        sessionStorage.removeItem(playgroundDraftKey(kb.id));
        toast.message('Using your unsaved retrieval settings as a draft');
      }
    } catch {
      // Storage can be blocked; keep the saved settings.
    }
  }, [kb.id]);
  React.useEffect(() => {
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, []);
  const last = turns[turns.length - 1];
  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns.length, last?.streamed.length, last?.result]);

  const isDraft = JSON.stringify(draft) !== JSON.stringify(kb.retrieval);
  const busy = turns.some((t) => t.streaming);
  const failed = kb.health === 'failed';
  const patchTurn = (tid: string, p: Partial<Turn>) => setTurns((ts) => ts.map((x) => (x.id === tid ? { ...x, ...p } : x)));

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setInput('');
    const tid = `t${Date.now()}`;
    const settings = draft;
    setTurns((ts) => [...ts, { id: tid, question: q, streamed: '', streaming: true, settings }]);
    try {
      const result = await query.mutateAsync({ question: q, settings, runAsId: runAsId ?? undefined });
      const text = result.noAnswer || !settings.synthesis ? '' : result.answer;
      patchTurn(tid, { result, streaming: !!text });
      if (!text) return;
      let i = 0;
      timer.current = setInterval(() => {
        i += 4;
        patchTurn(tid, { streamed: text.slice(0, i) });
        if (i >= text.length) {
          if (timer.current) clearInterval(timer.current);
          patchTurn(tid, { streaming: false, streamed: text });
        }
      }, 18);
    } catch (e) {
      patchTurn(tid, { streaming: false, error: `${(e as Error).message} Your settings were not changed.` });
    }
  };

  const stop = () => {
    if (timer.current) clearInterval(timer.current);
    setTurns((ts) => ts.map((x) => (x.streaming && x.result ? { ...x, streaming: false, result: { ...x.result, answer: x.streamed } } : x)));
  };

  const rail = (
    <div className="flex flex-col gap-4">
      <RetrievalForm
        value={draft}
        onChange={(p) => setDraft((d) => ({ ...d, ...p }))}
        sources={kb.attached.map((a) => ({ id: a.sourceId, name: a.source.name }))}
        metadataKeys={kb.metadataKeys}
        models={lookups.data?.models ?? []}
        variant="rail"
      />
      <div className="flex flex-wrap gap-2 border-t pt-4">
        <LoadingButton
          size="sm"
          isLoading={update.isPending}
          disabled={!isDraft}
          onClick={async () => {
            try {
              await update.mutateAsync({ retrieval: draft });
              toast.success(`Saved as ${kb.name}’s retrieval settings`);
            } catch (e) {
              toast.error('Couldn’t save settings', { description: (e as Error).message });
            }
          }}
        >
          <Save className="size-3.5" /> Save as defaults
        </LoadingButton>
        <Button size="sm" variant="outline" disabled={!isDraft} onClick={() => setDraft(kb.retrieval)}>
          <RotateCcw className="size-3.5" /> Reset to saved
        </Button>
      </div>
    </div>
  );

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-h-[60vh] min-w-0 flex-col gap-3">
        <RunAsBar principals={principals.data ?? []} loading={principals.isPending} value={runAsId} onChange={setRunAsId} />
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
        <div className="flex items-center justify-end xl:hidden">
          <Button variant="outline" size="sm" onClick={() => setRailOpen(true)}>
            <Settings2 className="size-3.5" /> Settings
            {isDraft && (
              <Badge variant="secondary" className="ml-1 font-normal">
                Draft
              </Badge>
            )}
          </Button>
        </div>

        <div className="flex flex-1 flex-col gap-4">
          {turns.length === 0 && (
            <div className="rounded-lg border border-dashed p-6">
              <p className="mb-3 text-sm font-medium">Try a question agents ask this knowledge base</p>
              <div className="flex flex-wrap gap-2">
                {kb.suggestedQuestions.map((q) => (
                  <button key={q} type="button" disabled={failed} onClick={() => ask(q)} className="rounded-full border px-3 py-1.5 text-left text-sm hover:bg-accent disabled:opacity-50">
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((t) =>
            t.result || t.error ? (
              <div key={t.id} className="flex flex-col gap-1.5">
                <QueryResult
                  result={t.result ?? { id: t.id, question: t.question, matchers: [], answer: '', citations: [], chunks: [], retrievalMs: 0, synthesisMs: 0 }}
                  streamed={t.streamed}
                  streaming={t.streaming}
                  settings={t.settings}
                  kbId={kb.id}
                  error={t.error}
                  onRetry={() => {
                    setTurns((ts) => ts.filter((y) => y.id !== t.id));
                    ask(t.question);
                  }}
                  onExclude={(docId) =>
                    exclude.mutate([docId], {
                      onSuccess: () => toast.success('Excluded from the index', { description: 'An exclude rule was added to its source.' }),
                      onError: (e) => toast.error('Couldn’t exclude', { description: e.message }),
                    })
                  }
                />
                <PermissionNote scope={t.result?.permissions} />
              </div>
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
                  ask(input);
                }
              }}
              placeholder={failed ? 'Questions are disabled while the last refresh is failed' : 'Ask a question…'}
              aria-label="Question"
              disabled={failed}
              rows={2}
              className="min-h-11 resize-none border-0 shadow-none focus-visible:ring-0"
            />
            {busy ? (
              <Button size="icon" variant="outline" onClick={stop} aria-label="Stop">
                <Square className="size-4" />
              </Button>
            ) : (
              <Button size="icon" onClick={() => ask(input)} disabled={!input.trim() || failed} aria-label="Send">
                <Send className="size-4" />
              </Button>
            )}
          </div>
          <div className="flex items-center justify-between px-1 pt-1 text-[11px] text-muted-foreground">
            <span>Enter to send · Shift+Enter for a new line</span>
            <span className={cn('hidden sm:inline', isDraft && 'text-amber-600 dark:text-amber-400')}>
              {isDraft ? 'Draft settings' : 'Saved settings'} · {draft.searchMode} · {draft.chunkLimit} chunks · ≥ {draft.threshold.toFixed(2)}
            </span>
          </div>
        </div>
      </div>

      {wide && (
      <aside>
        <div className="sticky top-4 rounded-lg border bg-card">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h2 className="text-sm font-semibold">Settings</h2>
            {isDraft && (
              <Badge variant="secondary" className="font-normal">
                Draft
              </Badge>
            )}
          </div>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto p-4">{rail}</div>
        </div>
      </aside>
      )}

      <DetailSheet open={railOpen && !wide} onOpenChange={setRailOpen} title="Settings" description="Overrides for this session until you save them as defaults" widthClass="sm:max-w-md">
        {rail}
      </DetailSheet>
    </div>
  );
}
