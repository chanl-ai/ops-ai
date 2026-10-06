'use client';

import * as React from 'react';
import { Columns2, RotateCcw, Save, Send, Settings2, Square } from 'lucide-react';
import { toast } from 'sonner';

import { KbDot } from '@/components/knowledge/knowledge-meta';
import { QueryResult } from '@/components/knowledge/query-result';
import { RetrievalForm } from '@/components/knowledge/retrieval-form';
import { MODE_LABEL, RUNTIME_VARIABLES, variablesIn } from '@/components/knowledge/retrieval-meta';
import { PermissionNote } from '@/components/run-as/permission-note';
import { RunAsBar } from '@/components/run-as/run-as-bar';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { LoadingButton } from '@/components/shared/loading-button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { useExcludeItems, useKbQuery, useKnowledgeBases, useUpdateKb } from '@/hooks/knowledge-queries';
import { useLookups } from '@/hooks/queries';
import { useRunAsPrincipals } from '@/hooks/run-as-queries';
import { count } from '@/lib/format';
import type { KnowledgeBaseDetail, PlaygroundAnswer, RetrievalSettings } from '@/lib/types/knowledge';
import type { RuntimeValues } from '@/lib/types/knowledge-retrieval';
import { cn } from '@/lib/utils';

import { playgroundDraftKey } from './kb-retrieval-tab';

interface Run {
  settings: RetrievalSettings;
  result?: PlaygroundAnswer;
  error?: string;
}

interface Turn {
  id: string;
  question: string;
  a: Run;
  /** The second configuration when comparing. */
  b?: Run;
  streamed: string;
  streaming: boolean;
  kbIds: string[];
  runtime: RuntimeValues;
}

const emptyResult = (id: string, question: string): PlaygroundAnswer => ({ id, question, matchers: [], answer: '', citations: [], chunks: [], retrievalMs: 0, synthesisMs: 0 });
const summary = (s: RetrievalSettings) => `${MODE_LABEL[s.searchMode]}${s.searchMode === 'hybrid' ? ` ${Math.round(s.hybridWeight * 100)}%` : s.searchMode === 'as_of' ? ` ${s.asOf || 'today'}` : ''}${s.rerank && s.searchMode !== 'table_lookup' ? ' · rerank' : ''} · ${s.chunkLimit} chunks · ≥ ${s.threshold.toFixed(2)}`;

/** Ask a question, see the answer, the passages and the trace behind it, compare two configurations, and tune until it is right. */
export function KbPlaygroundTab({ kb }: { kb: KnowledgeBaseDetail }) {
  const query = useKbQuery(kb.id);
  const update = useUpdateKb(kb.id);
  const exclude = useExcludeItems();
  const lookups = useLookups();
  const principals = useRunAsPrincipals();
  const otherKbs = useKnowledgeBases({ page: 1, pageSize: 50 });
  // Who questions run as; permissions remove what that person or role cannot read before ranking.
  const [runAsId, setRunAsId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState<RetrievalSettings>(kb.retrieval);
  const [compare, setCompare] = React.useState(false);
  const [draftB, setDraftB] = React.useState<RetrievalSettings>({ ...kb.retrieval, searchMode: kb.retrieval.searchMode === 'keyword' ? 'semantic' : 'keyword' });
  const [railTab, setRailTab] = React.useState('a');
  const [alsoKbIds, setAlsoKbIds] = React.useState<string[]>([]);
  const [runtime, setRuntime] = React.useState<RuntimeValues>({});
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
  }, [turns.length, last?.streamed.length, last?.a.result]);

  const isDraft = JSON.stringify(draft) !== JSON.stringify(kb.retrieval);
  const busy = turns.some((t) => t.streaming);
  const failed = kb.health === 'failed';
  const patchTurn = (tid: string, p: Partial<Turn>) => setTurns((ts) => ts.map((x) => (x.id === tid ? { ...x, ...p } : x)));
  const variables = Array.from(new Set([...draft.filters.conditions, ...(compare ? draftB.filters.conditions : [])].flatMap((c) => variablesIn(c.value))));
  const runtimeNow = Object.fromEntries(Object.entries(runtime).filter(([k, v]) => v.trim() && variables.includes(k)));
  const others = (otherKbs.data?.data ?? []).filter((k) => k.id !== kb.id);

  const runOne = async (question: string, settings: RetrievalSettings): Promise<Run> => {
    try {
      const result = await query.mutateAsync({ question, settings, runAsId: runAsId ?? undefined, alsoKbIds, runtime: runtimeNow });
      return { settings, result };
    } catch (e) {
      return { settings, error: `${(e as Error).message} Your settings were not changed.` };
    }
  };

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    setInput('');
    const tid = `t${Date.now()}`;
    const kbIds = [kb.id, ...alsoKbIds];
    setTurns((ts) => [...ts, { id: tid, question: q, a: { settings: draft }, b: compare ? { settings: draftB } : undefined, streamed: '', streaming: true, kbIds, runtime: runtimeNow }]);
    const [a, b] = await Promise.all([runOne(q, draft), compare ? runOne(q, draftB) : Promise.resolve(undefined)]);
    const text = a.result && !a.result.noAnswer ? a.result.answer : '';
    patchTurn(tid, { a, b, streaming: !!text });
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
  };

  const stop = () => {
    if (timer.current) clearInterval(timer.current);
    setTurns((ts) => ts.map((x) => (x.streaming && x.a.result ? { ...x, streaming: false, a: { ...x.a, result: { ...x.a.result, answer: x.streamed } } } : x)));
  };

  const form = (value: RetrievalSettings, onChange: (p: Partial<RetrievalSettings>) => void, idPrefix: string) => (
    <RetrievalForm value={value} onChange={onChange} sources={kb.attached.map((a) => ({ id: a.sourceId, name: a.source.name }))} metadataKeys={kb.metadataKeys} models={lookups.data?.models ?? []} variant="rail" idPrefix={idPrefix} />
  );

  const rail = (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2 rounded-md border bg-background px-3 py-2">
        <Label htmlFor="pg-compare" className="flex items-center gap-1.5 font-normal">
          <Columns2 className="size-3.5" /> Compare two configurations
        </Label>
        <Switch
          id="pg-compare"
          checked={compare}
          onCheckedChange={(on) => {
            setCompare(on);
            setRailTab(on ? 'b' : 'a');
          }}
        />
      </div>
      {compare ? (
        <Tabs value={railTab} onValueChange={setRailTab}>
          <TabsList className="w-full">
            <TabsTrigger value="a" className="flex-1">
              A
            </TabsTrigger>
            <TabsTrigger value="b" className="flex-1">
              B
            </TabsTrigger>
          </TabsList>
          <TabsContent value="a" className="pt-3">
            {form(draft, (p) => setDraft((d) => ({ ...d, ...p })), 'pg-a')}
          </TabsContent>
          <TabsContent value="b" className="pt-3">
            {form(draftB, (p) => setDraftB((d) => ({ ...d, ...p })), 'pg-b')}
          </TabsContent>
        </Tabs>
      ) : (
        form(draft, (p) => setDraft((d) => ({ ...d, ...p })), 'pg-a')
      )}

      <div className="flex flex-col gap-2 border-t pt-4">
        <Label>Also search</Label>
        <p className="text-xs text-muted-foreground">Their precedence rules apply after the rules of {kb.name}; the trace names which rule decided.</p>
        {others.length === 0 && <p className="text-xs text-muted-foreground">{otherKbs.isPending ? 'Loading knowledge bases…' : 'No other knowledge bases in this team.'}</p>}
        <div className="flex flex-col gap-1.5">
          {others.map((k) => (
            <label key={k.id} htmlFor={`pg-also-${k.id}`} className="flex cursor-pointer items-center gap-2 text-sm">
              <Checkbox id={`pg-also-${k.id}`} checked={alsoKbIds.includes(k.id)} onCheckedChange={(on) => setAlsoKbIds((ids) => (on ? [...ids, k.id] : ids.filter((x) => x !== k.id)))} />
              <KbDot color={k.color} /> {k.name}
            </label>
          ))}
        </div>
      </div>

      {variables.length > 0 && (
        <div className="flex flex-col gap-2 border-t pt-4" data-testid="runtime-values">
          <Label>Runtime values</Label>
          <p className="text-xs text-muted-foreground">What a live run would supply. Empty uses each filter’s preview value.</p>
          {variables.map((v) => (
            <div key={v} className="flex items-center gap-2">
              <label htmlFor={`pg-rt-${v}`} className="w-32 shrink-0 truncate font-mono text-xs" title={RUNTIME_VARIABLES.find((x) => x.name === v)?.label}>
                {v}
              </label>
              <Input id={`pg-rt-${v}`} className="h-8 font-mono text-xs" value={runtime[v] ?? ''} placeholder={`e.g. ${RUNTIME_VARIABLES.find((x) => x.name === v)?.example ?? 'value'}`} onChange={(e) => setRuntime((r) => ({ ...r, [v]: e.target.value }))} />
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2 border-t pt-4">
        <LoadingButton
          size="sm"
          isLoading={update.isPending}
          disabled={!isDraft}
          onClick={async () => {
            try {
              await update.mutateAsync({ retrieval: draft });
              toast.success(`Saved as the retrieval settings of ${kb.name}`, { description: compare ? 'Configuration A was saved.' : undefined });
            } catch (e) {
              toast.error('Couldn’t save settings', { description: (e as Error).message });
            }
          }}
        >
          <Save className="size-3.5" /> Save {compare ? 'A ' : ''}as defaults
        </LoadingButton>
        <Button size="sm" variant="outline" disabled={!isDraft} onClick={() => setDraft(kb.retrieval)}>
          <RotateCcw className="size-3.5" /> Reset to saved
        </Button>
      </div>
    </div>
  );

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
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
            {(isDraft || compare) && (
              <Badge variant="secondary" className="ml-1 font-normal">
                {compare ? 'Comparing' : 'Draft'}
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
          {turns.map((t) => {
            const done = !!(t.a.result || t.a.error);
            if (!done)
              return (
                <div key={t.id} className="rounded-lg border bg-card px-4 py-3 text-sm">
                  <p className="font-medium">{t.question}</p>
                  <p className="mt-1 animate-pulse text-xs text-muted-foreground">
                    Searching {kb.name}
                    {t.kbIds.length > 1 ? ` and ${t.kbIds.length - 1} more` : ''}…
                  </p>
                </div>
              );
            const retry = () => {
              setTurns((ts) => ts.filter((y) => y.id !== t.id));
              ask(t.question);
            };
            const card = (run: Run, label: string | undefined, streaming: boolean) => (
              <div className="flex min-w-0 flex-col gap-1.5">
                <QueryResult
                  result={run.result ?? emptyResult(t.id, t.question)}
                  streamed={t.streamed}
                  streaming={streaming}
                  settings={run.settings}
                  kbId={kb.id}
                  kbIds={t.kbIds}
                  runtime={t.runtime}
                  label={label}
                  error={run.error}
                  onRetry={retry}
                  onExclude={(docId) =>
                    exclude.mutate([docId], {
                      onSuccess: () => toast.success('Excluded from the index', { description: 'An exclude rule was added to its source.' }),
                      onError: (e) => toast.error('Couldn’t exclude', { description: e.message }),
                    })
                  }
                />
                <PermissionNote scope={run.result?.permissions} />
              </div>
            );
            return t.b ? (
              <div key={t.id} className="grid gap-3 2xl:grid-cols-2" data-testid="compare-pair">
                {card(t.a, 'A', t.streaming)}
                {card(t.b, 'B', false)}
              </div>
            ) : (
              <React.Fragment key={t.id}>{card(t.a, undefined, t.streaming)}</React.Fragment>
            );
          })}
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
          <div className="flex items-center justify-between gap-2 px-1 pt-1 text-[11px] text-muted-foreground">
            <span>Enter to send · Shift+Enter for a new line</span>
            <span className={cn('hidden truncate sm:inline', isDraft && 'text-amber-600 dark:text-amber-400')}>
              {compare ? `A: ${summary(draft)} · B: ${summary(draftB)}` : `${isDraft ? 'Draft settings' : 'Saved settings'} · ${summary(draft)}`}
              {alsoKbIds.length ? ` · +${alsoKbIds.length} knowledge ${alsoKbIds.length === 1 ? 'base' : 'bases'}` : ''}
            </span>
          </div>
        </div>
      </div>

      {wide && (
        <aside>
          <div className="sticky top-4 rounded-lg border bg-card">
            <div className="flex items-center justify-between border-b px-4 py-3">
              <h2 className="text-sm font-semibold">Settings for this session</h2>
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
