'use client';

import * as React from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { PromptAnalysis, PromptContext, PromptSection, PromptSpec, RewriteSectionInput } from '@/lib/types/prompts';
import type { ListParams } from '@/lib/types/query';

export const pk = {
  variables: ['prompt-variables'] as const,
};

export const usePromptVariables = () => useQuery({ queryKey: pk.variables, queryFn: api.prompts.variables, staleTime: 10 * 60_000 });

export const useAnalyzePrompt = () => useMutation({ mutationFn: ({ sections, context }: { sections: PromptSection[]; context: PromptContext }) => api.prompts.analyze(sections, context) });
export const useRewriteSection = () => useMutation({ mutationFn: (i: RewriteSectionInput) => api.prompts.rewriteSection(i) });

export type GenerationStatus = 'idle' | 'streaming' | 'stopped' | 'done' | 'error';

/**
 * Runs one generation and keeps its sections as they stream in. `stop` aborts the request and keeps the text so
 * far; `setSections` takes per-section rewrites and lint fixes, which change the prompt without regenerating it.
 */
export function useGeneratePrompt() {
  const [sections, setSections] = React.useState<PromptSection[]>([]);
  const [analysis, setAnalysis] = React.useState<PromptAnalysis | null>(null);
  const [status, setStatus] = React.useState<GenerationStatus>('idle');
  const [error, setError] = React.useState<string | null>(null);
  const abort = React.useRef<AbortController | null>(null);

  const start = React.useCallback(async (spec: PromptSpec, context: PromptContext) => {
    abort.current?.abort();
    const ctrl = new AbortController();
    abort.current = ctrl;
    setSections([]);
    setAnalysis(null);
    setError(null);
    setStatus('streaming');
    try {
      for await (const ev of api.prompts.generate(spec, context, ctrl.signal)) {
        if (ctrl.signal.aborted) break;
        if (ev.type === 'section') setSections((s) => [...s, { ...ev.section, body: '' }]);
        else if (ev.type === 'delta') setSections((s) => s.map((x) => (x.id === ev.sectionId ? { ...x, body: x.body + ev.text } : x)));
        else setAnalysis(ev.analysis);
      }
      setStatus(ctrl.signal.aborted ? 'stopped' : 'done');
    } catch (e) {
      if (ctrl.signal.aborted) return setStatus('stopped');
      setError((e as Error).message);
      setStatus('error');
    }
  }, []);

  const stop = React.useCallback(() => {
    abort.current?.abort();
    setStatus('stopped');
  }, []);

  React.useEffect(() => {
    return () => abort.current?.abort();
  }, []);

  return { sections, setSections, analysis, setAnalysis, status, error, start, stop };
}

/** Everything the prompt generator dialog needs from the API, assembled once per page. */
export function usePromptGenerator() {
  const variables = usePromptVariables();
  const generation = useGeneratePrompt();
  const analyze = useAnalyzePrompt();
  const rewrite = useRewriteSection();
  return {
    variables: variables.data ?? [],
    generation,
    analyze: (sections: PromptSection[], context: PromptContext) => analyze.mutateAsync({ sections, context }),
    rewrite: (input: RewriteSectionInput) => rewrite.mutateAsync(input),
    busy: analyze.isPending || rewrite.isPending,
  };
}

export type PromptGeneratorBackend = ReturnType<typeof usePromptGenerator>;
