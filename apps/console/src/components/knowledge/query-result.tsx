'use client';

import * as React from 'react';
import Link from 'next/link';
import { AlertTriangle, ExternalLink, FileText, MinusCircle, RotateCcw, Scale } from 'lucide-react';

import { CopyButton } from '@/components/shared/copy-button';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Toggle } from '@/components/ui/toggle';
import { ms } from '@/lib/format';
import type { Citation, PlaygroundAnswer, RetrievalSettings } from '@/lib/types/knowledge';
import type { RuntimeValues } from '@/lib/types/knowledge-retrieval';
import { cn } from '@/lib/utils';

import { CitationFlags } from './citation-flags';
import { MODE_LABEL, SHAPE_LABEL } from './retrieval-meta';
import { RetrievalTraceView } from './retrieval-trace';

const docHref = (kbId: string, documentId: string) => `/knowledge/${kbId}?tab=documents&doc=${documentId}`;

function CitationMarker({ citation: c, kbId }: { citation: Citation; kbId: string }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded border bg-muted px-1 align-text-top font-mono text-[10px] font-medium hover:bg-accent" aria-label={`Citation ${c.n}: ${c.title}`}>
          {c.n}
        </button>
      </PopoverTrigger>
      <PopoverContent className="flex w-80 flex-col gap-2 text-sm" align="start">
        <div className="flex items-start gap-2">
          <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <div className="font-medium leading-snug">{c.title}</div>
            <div className="text-xs text-muted-foreground">
              {c.section}
              {c.page ? ` · p.${c.page}` : ''} · <span className="font-mono">{c.version}</span>
            </div>
            <CitationFlags citation={c} className="mt-1" />
          </div>
        </div>
        <p className="rounded bg-muted/50 p-2 text-xs italic">“{c.snippet}”</p>
        <div className="flex flex-wrap gap-1.5">
          <Button asChild size="sm" variant="outline" className="h-7">
            <Link href={docHref(kbId, c.documentId)}>Open document</Link>
          </Button>
          {c.url && (
            <Button asChild size="sm" variant="ghost" className="h-7">
              <a href={c.url} target="_blank" rel="noreferrer">
                <ExternalLink className="size-3.5" /> Open at source
              </a>
            </Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** Answer text with [n] markers turned into citation popovers. */
function CitedText({ text, citations, kbId }: { text: string; citations: Citation[]; kbId: string }) {
  return (
    <p className="text-sm leading-relaxed whitespace-pre-wrap">
      {text.split(/(\[\^?\d+\])/g).map((p, i) => {
        const m = p.match(/^\[\^?(\d+)\]$/);
        const c = m && citations.find((x) => x.n === Number(m[1]));
        return c ? <CitationMarker key={i} citation={c} kbId={kbId} /> : <span key={i}>{p}</span>;
      })}
    </p>
  );
}

/** One playground turn: the answer with citations, the scored chunks behind it, and the request that reproduces it. */
export function QueryResult({
  result,
  streamed,
  streaming,
  settings,
  kbId,
  error,
  onRetry,
  onExclude,
  kbIds,
  runtime,
  label,
}: {
  result: PlaygroundAnswer;
  streamed?: string;
  streaming?: boolean;
  settings: RetrievalSettings;
  kbId: string;
  error?: string | null;
  onRetry?: () => void;
  onExclude?: (documentId: string) => void;
  /** Every knowledge base the question searched, for the request body. */
  kbIds?: string[];
  runtime?: RuntimeValues;
  /** Names the configuration when two results sit side by side. */
  label?: string;
}) {
  const [showRejected, setShowRejected] = React.useState(false);
  const chunks = result.chunks.filter((c) => showRejected || !c.rejected);
  const shape = result.shape ?? settings.answerShape;
  const body = {
    question: result.question,
    kbIds: kbIds ?? [kbId],
    settings: {
      searchMode: settings.searchMode,
      ...(settings.searchMode === 'hybrid' ? { hybridWeight: settings.hybridWeight } : {}),
      ...(settings.searchMode === 'as_of' ? { asOf: settings.asOf || 'today' } : {}),
      rerank: settings.rerank,
      rewrite: settings.rewrite,
      ...(settings.rewrite === 'expand' ? { expandCount: settings.expandCount } : {}),
      chunkLimit: settings.chunkLimit,
      threshold: settings.threshold,
      answerShape: settings.answerShape,
      ...(settings.answerShape !== 'chunks' ? { model: settings.model, temperature: settings.temperature, instructions: settings.instructions, citationStyle: settings.citationStyle } : {}),
    },
    filters: { match: settings.filters.match, conditions: settings.filters.conditions.map(({ key, op, value }) => ({ key, op, value })), tags: { include: settings.tagsInclude, exclude: settings.tagsExclude, includeUntagged: settings.includeUntagged }, sourceIds: settings.scopeSourceIds },
    ...(runtime && Object.keys(runtime).length ? { runtime } : {}),
  };
  const json = JSON.stringify(body, null, 2);

  return (
    <div className="rounded-lg border bg-card">
      <div className="flex items-start gap-3 border-b px-4 py-3">
        <span className="mt-0.5 rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{label ?? 'Q'}</span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{result.question}</p>
          <p className="text-xs text-muted-foreground">
            {MODE_LABEL[settings.searchMode]}
            {settings.searchMode === 'hybrid' ? ` ${Math.round(settings.hybridWeight * 100)}% semantic` : ''}
            {settings.searchMode === 'as_of' ? ` ${settings.asOf || 'today'}` : ''}
            {settings.rerank && settings.searchMode !== 'table_lookup' ? ' · rerank' : ''}
            {settings.rewrite !== 'off' ? ` · ${settings.rewrite === 'expand' ? `${settings.expandCount} phrasings` : 'rewritten'}` : ''} · {SHAPE_LABEL[shape]}
            {settings.filters.conditions.length ? ` · ${settings.filters.conditions.length} ${settings.filters.conditions.length === 1 ? 'filter' : 'filters'}` : ''}
          </p>
        </div>
      </div>
      {error ? (
        <div className="p-4">
          <Alert variant="destructive">
            <AlertTriangle className="size-4" />
            <AlertTitle>The query did not complete</AlertTitle>
            <AlertDescription className="flex flex-col items-start gap-2">
              <p>{error}</p>
              {onRetry && (
                <Button size="sm" variant="outline" className="border-destructive/40 text-foreground" onClick={onRetry}>
                  <RotateCcw className="size-3.5" /> Try again
                </Button>
              )}
            </AlertDescription>
          </Alert>
        </div>
      ) : (
        <Tabs defaultValue="answer">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2">
            <TabsList className="h-8">
              <TabsTrigger value="answer" className="h-7 text-xs">
                Answer
              </TabsTrigger>
              <TabsTrigger value="chunks" className="h-7 text-xs">
                Chunks <span className="ml-1 text-muted-foreground">({result.chunks.filter((c) => !c.rejected).length})</span>
              </TabsTrigger>
              {result.trace && (
                <TabsTrigger value="trace" className="h-7 text-xs">
                  Trace
                </TabsTrigger>
              )}
              <TabsTrigger value="request" className="h-7 text-xs">
                Request
              </TabsTrigger>
            </TabsList>
            {!streaming && (
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="outline" className="font-normal tabular-nums">
                  {ms(result.retrievalMs)} retrieval
                </Badge>
                {result.synthesisMs > 0 && (
                  <Badge variant="outline" className="font-normal tabular-nums">
                    {ms(result.synthesisMs)} synthesis
                  </Badge>
                )}
              </div>
            )}
          </div>
          <TabsContent value="answer" className="flex flex-col gap-3 p-4">
            {result.noAnswer && !streaming ? (
              <div className="flex flex-col gap-3">
                <div className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900 dark:bg-amber-950/40">
                  <MinusCircle className="mt-0.5 size-4 shrink-0 text-amber-600" />
                  <div>
                    <div className="font-medium">No answer</div>
                    <p className="text-muted-foreground">{settings.noAnswerMessage}</p>
                  </div>
                </div>
                {result.chunks.length > 0 && (
                  <div>
                    <p className="mb-1.5 text-xs text-muted-foreground">Closest chunks, below the {settings.threshold.toFixed(2)} threshold:</p>
                    <div className="rounded-md border">
                      <Table>
                        <TableBody>
                          {result.chunks.map((c) => (
                            <TableRow key={c.chunkId}>
                              <TableCell className="w-14 font-mono text-xs tabular-nums text-muted-foreground">{c.score.toFixed(2)}</TableCell>
                              <TableCell className="max-w-0 truncate">
                                {c.documentTitle} <span className="text-xs text-muted-foreground">· {c.location}</span>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </div>
                )}
              </div>
            ) : shape === 'chunks' && !streaming ? (
              <div className="flex flex-col gap-2">
                <p className="text-sm text-muted-foreground">Chunks only: no answer is written. These passages go to the workflow step that asked.</p>
                <ol className="flex flex-col gap-1.5">
                  {result.chunks
                    .filter((c) => !c.rejected)
                    .map((c, i) => (
                      <li key={c.chunkId} className="rounded-md border p-2 text-xs">
                        <div className="mb-0.5 text-muted-foreground">
                          {i + 1}. {c.documentTitle} · {c.location} · <span className="font-mono">{c.score.toFixed(2)}</span>
                        </div>
                        <p className="whitespace-pre-wrap">{c.text}</p>
                      </li>
                    ))}
                </ol>
              </div>
            ) : (
              <>
                <CitedText text={streaming ? (streamed ?? '') : result.answer} citations={result.citations} kbId={kbId} />
                {streaming && <span className="inline-block h-4 w-1.5 animate-pulse bg-foreground/70 align-middle" />}
                {!streaming && result.rows && result.rows.length > 0 && (
                  <div className="overflow-x-auto rounded-md border" data-testid="table-rows">
                    <div className="border-b bg-muted/40 px-3 py-1.5 text-xs font-medium">
                      Matched rows · {result.rows[0].documentTitle} {result.rows[0].version}
                    </div>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Row</TableHead>
                          {Object.keys(result.rows[0].values).map((k) => (
                            <TableHead key={k}>{k}</TableHead>
                          ))}
                          <TableHead className="text-right">Score</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {result.rows.map((r) => (
                          <TableRow key={`${r.documentId}-${r.row}`}>
                            <TableCell className="font-mono text-xs">{r.row}</TableCell>
                            {Object.entries(r.values).map(([k, val]) => (
                              <TableCell key={k} className={cn('text-xs whitespace-nowrap', r.matched.includes(k) && 'font-medium text-primary')}>
                                {val}
                              </TableCell>
                            ))}
                            <TableCell className="text-right font-mono text-xs tabular-nums">{r.score.toFixed(2)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
                {!streaming && result.structured && settings.structuredTables && (
                  <div className="overflow-hidden rounded-md border">
                    <div className="border-b bg-muted/40 px-3 py-1.5 text-xs font-medium">Structured values</div>
                    <Table>
                      <TableBody>
                        {result.structured.map((s) => (
                          <TableRow key={s.label}>
                            <TableCell className="text-muted-foreground">{s.label}</TableCell>
                            <TableCell className="text-right font-mono tabular-nums">
                              {s.value}
                              {s.unit && <span className="ml-1 text-muted-foreground">{s.unit}</span>}
                            </TableCell>
                            <TableCell className="hidden text-right text-xs text-muted-foreground sm:table-cell">{s.from}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
                {!streaming && result.followed && (
                  <p className="flex items-start gap-2 text-xs text-muted-foreground">
                    <Scale className="mt-0.5 size-3.5 shrink-0" />
                    <span>Followed: {result.followed}</span>
                  </p>
                )}
                {!streaming && result.citations.length > 0 && (
                  <ol className="flex flex-col gap-1 border-t pt-3">
                    {result.citations.map((c) => (
                      <li key={c.n} className="flex items-start gap-2 text-xs">
                        <span className="mt-0.5 rounded border bg-muted px-1 font-mono text-[10px]">{c.n}</span>
                        <span className="min-w-0 text-muted-foreground">
                          <Link href={docHref(kbId, c.documentId)} className="text-foreground hover:underline">
                            {c.title}
                          </Link>{' '}
                          · {c.section}
                          {c.page ? ` · p.${c.page}` : ''} · <span className="font-mono">{c.version}</span>
                        </span>
                        <CitationFlags citation={c} />
                      </li>
                    ))}
                  </ol>
                )}
              </>
            )}
          </TabsContent>
          <TabsContent value="chunks" className="p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">Ordered by final score. Threshold {settings.threshold.toFixed(2)}; the Trace tab shows every stage.</p>
              <Toggle size="sm" pressed={showRejected} onPressedChange={setShowRejected} className="h-7 text-xs">
                Show rejected
              </Toggle>
            </div>
            {chunks.length === 0 ? (
              <p className="rounded-md border p-4 text-sm text-muted-foreground">Nothing passed the threshold. Show rejected chunks to see what came close.</p>
            ) : (
              <Accordion type="multiple" className="rounded-md border">
                {chunks.map((c, i) => (
                  <AccordionItem key={c.chunkId} value={c.chunkId} className={cn('px-3', c.rejected && 'opacity-60')}>
                    <AccordionTrigger className="py-2 text-sm hover:no-underline">
                      <span className="flex min-w-0 flex-1 items-center gap-3">
                        <span className="w-5 text-xs tabular-nums text-muted-foreground">{i + 1}</span>
                        <span className={cn('w-12 font-mono text-xs tabular-nums', c.rejected && 'text-muted-foreground line-through')}>{c.score.toFixed(2)}</span>
                        <span className="min-w-0 flex-1 truncate text-left">{c.documentTitle}</span>
                        <span className="hidden truncate text-xs text-muted-foreground sm:inline">
                          {c.sourceName} · {c.location}
                        </span>
                      </span>
                    </AccordionTrigger>
                    <AccordionContent className="flex flex-col gap-2">
                      <p className="text-sm leading-relaxed">{c.text}</p>
                      <div className="flex flex-wrap gap-1.5">
                        <Button asChild size="sm" variant="outline" className="h-7">
                          <Link href={docHref(kbId, c.documentId)}>Open document</Link>
                        </Button>
                        {onExclude && (
                          <Button size="sm" variant="ghost" className="h-7" onClick={() => onExclude(c.documentId)}>
                            <MinusCircle className="size-3.5" /> Exclude document
                          </Button>
                        )}
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                ))}
              </Accordion>
            )}
          </TabsContent>
          {result.trace && (
            <TabsContent value="trace" className="p-4">
              <RetrievalTraceView trace={result.trace} />
            </TabsContent>
          )}
          <TabsContent value="request" className="flex flex-col gap-3 p-4">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">The request body that reproduces this result.</p>
              <CopyButton text={json} variant="outline" />
            </div>
            <pre className="max-h-72 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed">{json}</pre>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
