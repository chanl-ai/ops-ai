'use client';

import * as React from 'react';
import { ArrowRight, Play, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { RETRIEVAL_PRESETS } from '@/components/knowledge/knowledge-meta';
import { RetrievalForm } from '@/components/knowledge/retrieval-form';
import { MODE_LABEL, OP_LABEL, REWRITE_LABEL, SHAPE_LABEL } from '@/components/knowledge/retrieval-meta';
import { LoadingButton } from '@/components/shared/loading-button';
import { KeyValues, Section } from '@/components/shared/surface';
import { TagInput } from '@/components/shared/tag-input';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useUpdateKb } from '@/hooks/knowledge-queries';
import { useLookups } from '@/hooks/queries';
import { plural } from '@/lib/format';
import type { KnowledgeBaseDetail, MetadataProfile, PrecedenceRule, RetrievalSettings } from '@/lib/types/knowledge';

/** Session hand-off of unsaved retrieval settings from this tab to the playground. */
export const playgroundDraftKey = (kbId: string) => `ops-playground-draft-${kbId}`;

/** Retrieval settings form with precedence rules, a live summary rail and a sticky unsaved bar. */
export function KbRetrievalTab({ kb, onTestInPlayground }: { kb: KnowledgeBaseDetail; onTestInPlayground: () => void }) {
  const update = useUpdateKb(kb.id);
  const lookups = useLookups();
  const [draft, setDraft] = React.useState<RetrievalSettings>(kb.retrieval);
  const [precedence, setPrecedence] = React.useState<PrecedenceRule[]>(kb.precedence);
  const [profile, setProfile] = React.useState<MetadataProfile>(kb.metadataProfile);
  React.useEffect(() => {
    setDraft(kb.retrieval);
    setPrecedence(kb.precedence);
    setProfile(kb.metadataProfile);
  }, [kb.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = JSON.stringify(draft) !== JSON.stringify(kb.retrieval) || JSON.stringify(precedence) !== JSON.stringify(kb.precedence) || JSON.stringify(profile) !== JSON.stringify(kb.metadataProfile);
  React.useEffect(() => {
    if (!dirty) return;
    const guard = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [dirty]);

  const save = async () => {
    try {
      const profileChanged = JSON.stringify(profile) !== JSON.stringify(kb.metadataProfile);
      await update.mutateAsync({ retrieval: draft, precedence: precedence.filter((p) => p.label.trim()), metadataProfile: profile });
      toast.success('Retrieval settings saved', { description: profileChanged ? 'Documents missing a required field are held until it is supplied; the Documents tab lists them.' : 'They apply to the next query; stored chunks are unchanged.' });
    } catch (e) {
      toast.error('Couldn’t save retrieval settings', { description: (e as Error).message });
    }
  };
  const discard = () => {
    const before = { draft, precedence, profile };
    setDraft(kb.retrieval);
    setPrecedence(kb.precedence);
    setProfile(kb.metadataProfile);
    toast('Changes discarded', {
      action: {
        label: 'Undo',
        onClick: () => {
          setDraft(before.draft);
          setPrecedence(before.precedence);
          setProfile(before.profile);
        },
      },
    });
  };
  const testInPlayground = () => {
    try {
      sessionStorage.setItem(playgroundDraftKey(kb.id), JSON.stringify(draft));
    } catch {
      // Storage can be blocked; the playground then starts from the saved settings.
    }
    onTestInPlayground();
  };
  const setP = (i: number, p: Partial<PrecedenceRule>) => setPrecedence(precedence.map((x, j) => (j === i ? { ...x, ...p } : x)));

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-4">
          <RetrievalForm
            value={draft}
            onChange={(p) => setDraft((d) => ({ ...d, ...p }))}
            sources={kb.attached.map((a) => ({ id: a.sourceId, name: a.source.name }))}
            metadataKeys={kb.metadataKeys}
            models={lookups.data?.models ?? []}
            variant="full"
          />
          <Section id="precedence" title="Precedence" description="When two returned passages cover the same topic, the first matching rule decides which is used, and the answer and trace name the rule">
            <div className="flex flex-col gap-2">
              {precedence.map((p, i) => (
                <div key={p.id} className="flex flex-wrap items-center gap-2">
                  <span className="w-5 text-xs tabular-nums text-muted-foreground">{i + 1}</span>
                  <Input className="h-8 min-w-40 flex-1" value={p.label} onChange={(e) => setP(i, { label: e.target.value })} placeholder="e.g. Policy beats FAQ" aria-label="Rule" />
                  <Select value={p.kind} onValueChange={(k) => setP(i, { kind: k as PrecedenceRule['kind'] })}>
                    <SelectTrigger className="h-8 w-48" aria-label="Rule type">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="class">Document class wins</SelectItem>
                      <SelectItem value="newer">Newer effective date wins</SelectItem>
                    </SelectContent>
                  </Select>
                  {p.kind === 'class' && (
                    <>
                      <Input list="doc-classes" className="h-8 w-32 font-mono text-xs" value={p.winner} onChange={(e) => setP(i, { winner: e.target.value })} placeholder="e.g. policy" aria-label="Winning class" />
                      <ArrowRight className="size-3.5 text-muted-foreground" />
                      <Input list="doc-classes" className="h-8 w-32 font-mono text-xs" value={p.loser} onChange={(e) => setP(i, { loser: e.target.value })} placeholder="e.g. faq" aria-label="Losing class" />
                    </>
                  )}
                  <Button variant="ghost" size="icon" className="size-8" onClick={() => setPrecedence(precedence.filter((_, j) => j !== i))} aria-label="Remove rule">
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              ))}
              <datalist id="doc-classes">
                {['policy', 'procedure', 'playbook', 'guide', 'guidance', 'addendum', 'faq', 'pricing', 'schedule', 'model_doc', 'reference', 'form'].map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
              <Button variant="outline" size="sm" className="h-7 w-fit" onClick={() => setPrecedence([...precedence, { id: `p${Date.now()}`, label: '', kind: 'class', winner: '', loser: '' }])}>
                <Plus className="size-3.5" /> Add rule
              </Button>
            </div>
          </Section>
          <Section id="required-metadata" title="Required metadata" description="Documents missing any of these are held: stored, listed with the reason, and not searched until the field is supplied">
            <TagInput id="required-metadata" value={profile.required} onChange={(required) => setProfile({ required })} suggestions={kb.metadataKeys.filter((k) => !profile.required.includes(k))} placeholder="e.g. jurisdiction" />
            <p className="text-xs text-muted-foreground">
              {kb.heldCount ? `${plural(kb.heldCount, 'document')} held now.` : 'No documents held now.'} Owner and effective date come from each document; other keys come from the source’s metadata mapping.
            </p>
          </Section>
        </div>
        <div className="flex flex-col gap-4 lg:sticky lg:top-4 lg:self-start">
          <Section title="Effective settings" description="What a query gets with these settings" bodyClassName="px-4 py-1">
            <KeyValues
              rows={[
                ['Mode', `${MODE_LABEL[draft.searchMode]}${draft.searchMode === 'hybrid' ? ` · ${Math.round(draft.hybridWeight * 100)}% semantic` : draft.searchMode === 'as_of' ? ` · ${draft.asOf || 'today'}` : ''}`],
                ['Rerank', draft.rerank && draft.searchMode !== 'table_lookup' ? `On · ${draft.reranker}` : 'Off'],
                ['Rewriting', draft.rewrite === 'expand' ? `${draft.expandCount} phrasings` : REWRITE_LABEL[draft.rewrite]],
                ['Chunks', String(draft.chunkLimit)],
                ['Threshold', draft.threshold.toFixed(2)],
                ['Answer', draft.answerShape === 'chunks' ? SHAPE_LABEL.chunks : `${SHAPE_LABEL[draft.answerShape]} · ${draft.model}`],
                ['Citations', draft.citationStyle],
                ['Filters', draft.filters.conditions.length ? draft.filters.conditions.map((f) => `${f.key} ${OP_LABEL[f.op]}${f.op === 'exists' ? '' : ` ${f.value}`}`).join(draft.filters.match === 'all' ? ' and ' : ' or ') : 'None'],
                ['Required', profile.required.join(', ') || 'None'],
                ['Scope', draft.scopeSourceIds.length ? `${draft.scopeSourceIds.length} sources` : 'All sources'],
              ]}
            />
          </Section>
          <Section title="Start from a preset" description="Replaces search and synthesis settings; save to keep it">
            <div className="flex flex-wrap gap-2">
              {(Object.keys(RETRIEVAL_PRESETS) as (keyof typeof RETRIEVAL_PRESETS)[]).map((p) => (
                <Button key={p} variant="outline" size="sm" className="capitalize" onClick={() => setDraft((d) => ({ ...d, ...RETRIEVAL_PRESETS[p] }))}>
                  {p === 'raw' ? 'Raw retrieval' : p}
                </Button>
              ))}
            </div>
          </Section>
          <Button variant="outline" onClick={testInPlayground}>
            <Play className="size-3.5" /> Test in playground
          </Button>
        </div>
      </div>

      {dirty && (
        <div data-unsaved-bar className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-background/95 px-4 py-3 shadow-sm backdrop-blur">
          <span className="text-sm text-muted-foreground">Unsaved retrieval changes</span>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={discard} disabled={update.isPending}>
              <RotateCcw className="size-3.5" /> Discard
            </Button>
            <LoadingButton size="sm" isLoading={update.isPending} onClick={save}>
              Save changes
            </LoadingButton>
          </div>
        </div>
      )}
    </div>
  );
}
