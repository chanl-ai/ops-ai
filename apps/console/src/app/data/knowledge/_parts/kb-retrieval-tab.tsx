'use client';

import * as React from 'react';
import { toast } from 'sonner';

import { FormField } from '@/components/shared/form-field';
import { PageSaveActions } from '@/components/shared/page-save-actions';
import { SettingsField, SettingsSection } from '@/components/shared/settings-section';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useUpdateKb } from '@/hooks/knowledge-queries';
import type { KnowledgeBaseDetail, RetrievalSettings } from '@/lib/types/knowledge';

/** The lanes kb-service searches with: words in common, closeness of meaning, or both fused by rank. */
const MODES = [
  { value: 'hybrid', label: 'Meaning and keyword', hint: 'Both lanes, fused by rank. Keyword only while pieces are being embedded.' },
  { value: 'meaning', label: 'Meaning only', hint: 'Pieces close in meaning to the question.' },
  { value: 'keyword', label: 'Keyword only', hint: 'Pieces that share the question’s words.' },
] as const;
type Mode = (typeof MODES)[number]['value'];

/** The settings kb-service applies to every search of this base, with the two optional model steps around it. */
type Search = { searchMode: Mode; hybridWeight: number; threshold: number; chunkLimit: number; rerank: boolean; rewrite: 'off' | 'rewrite'; rewriteInstructions: string; queryModel: string };
const INSTRUCTION_MAX = 1000;
const LIMIT_MAX = 20;

const searchOf = (r: RetrievalSettings): Search => ({
  searchMode: (MODES.some((m) => m.value === r.searchMode) ? r.searchMode : 'hybrid') as Mode,
  hybridWeight: r.hybridWeight,
  threshold: r.threshold,
  chunkLimit: r.chunkLimit,
  rerank: !!r.rerank,
  rewrite: r.rewrite === 'rewrite' ? 'rewrite' : 'off',
  rewriteInstructions: r.rewriteInstructions ?? '',
  queryModel: r.queryModel ?? '',
});

function errorsOf(s: Search) {
  return {
    hybridWeight: s.hybridWeight >= 0 && s.hybridWeight <= 1 ? undefined : 'Between 0 and 1.',
    threshold: s.threshold >= 0 && s.threshold <= 1 ? undefined : 'Between 0 and 1.',
    chunkLimit: Number.isInteger(s.chunkLimit) && s.chunkLimit >= 1 && s.chunkLimit <= LIMIT_MAX ? undefined : `A whole number from 1 to ${LIMIT_MAX}.`,
    rewriteInstructions: s.rewriteInstructions.length <= INSTRUCTION_MAX ? undefined : `At most ${INSTRUCTION_MAX.toLocaleString()} characters.`,
  };
}

/**
 * How this base is searched: the mode, the weight toward meaning, the threshold and how many pieces come back, and the
 * optional rerank and rewrite steps. kb-service applies these to every search of the base (agents, the query route and
 * the Playground); saving sends only them.
 */
export function KbRetrievalTab({ kb }: { kb: KnowledgeBaseDetail }) {
  const update = useUpdateKb(kb.id);
  const saved = searchOf(kb.retrieval);
  const [draft, setDraft] = React.useState<Search>(saved);
  React.useEffect(() => {
    setDraft(searchOf(kb.retrieval));
  }, [kb.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const set = (p: Partial<Search>) => setDraft((d) => ({ ...d, ...p }));
  const errors = errorsOf(draft);
  const invalid = Object.values(errors).some(Boolean);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  const save = async () => {
    try {
      await update.mutateAsync({ retrieval: draft });
      toast.success('Search settings saved', { description: 'They apply to the next search of this knowledge base.' });
    } catch (e) {
      toast.error('Couldn’t save the search settings', { description: (e as Error).message });
    }
  };

  return (
    <div className="flex flex-col gap-4" data-testid="kb-retrieval">
      <SettingsSection title="Search" description="Applied to every search of this knowledge base: by agents, the query route and the Playground.">
        <div className="flex flex-col gap-5">
          <FormField id="ret-mode" label="Mode" hint={MODES.find((m) => m.value === draft.searchMode)?.hint}>
            <Select value={draft.searchMode} onValueChange={(v) => set({ searchMode: v as Mode })}>
              <SelectTrigger id="ret-mode" className="w-60 bg-background">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MODES.map((m) => (
                  <SelectItem key={m.value} value={m.value}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {draft.searchMode === 'hybrid' && (
            <NumberSlider id="ret-weight" label="Weight toward meaning" hint="0 is keyword only, 1 is meaning only." value={draft.hybridWeight} min={0} max={1} step={0.05} error={errors.hybridWeight} onChange={(v) => set({ hybridWeight: v })} />
          )}
          <NumberSlider id="ret-threshold" label="Threshold" hint="A piece scoring under it in a lane is dropped from that lane. With nothing above it, nothing comes back." value={draft.threshold} min={0} max={1} step={0.05} error={errors.threshold} onChange={(v) => set({ threshold: v })} />
          <FormField id="ret-limit" label="Pieces returned" hint={`At most this many, and at most two from one item. 1 to ${LIMIT_MAX}.`} error={errors.chunkLimit}>
            <Input id="ret-limit" type="number" className="w-24 bg-background tabular-nums" min={1} max={LIMIT_MAX} step={1} value={draft.chunkLimit} onChange={(e) => set({ chunkLimit: Number(e.target.value) })} aria-invalid={!!errors.chunkLimit} />
          </FormField>
        </div>
      </SettingsSection>

      <SettingsSection title="Before and after the search" description="Two model steps, both off until you turn them on. Each is one model call per question; when the model cannot answer, the search runs without the step and says so.">
        <div className="flex flex-col gap-5">
          <SettingsField label="Rerank" description="A model scores the best 20 pieces from 0 to 10 for how well they answer the question, and the pieces returned follow its order." htmlFor="ret-rerank">
            <Switch id="ret-rerank" checked={draft.rerank} onCheckedChange={(v) => set({ rerank: v })} data-testid="kb-retrieval-rerank" />
          </SettingsField>
          <SettingsField label="Rewrite the question" description="A model rewrites the question with your instruction before it is searched. The Playground shows the question as asked and as searched." htmlFor="ret-rewrite">
            <Switch id="ret-rewrite" checked={draft.rewrite === 'rewrite'} onCheckedChange={(v) => set({ rewrite: v ? 'rewrite' : 'off' })} data-testid="kb-retrieval-rewrite" />
          </SettingsField>
          {draft.rewrite === 'rewrite' && (
            <FormField id="ret-instruction" label="Rewrite instruction" hint="For example: name the product the customer asks about, and use the bank’s terms for it." error={errors.rewriteInstructions}>
              <Textarea id="ret-instruction" rows={3} value={draft.rewriteInstructions} onChange={(e) => set({ rewriteInstructions: e.target.value })} aria-invalid={!!errors.rewriteInstructions} data-testid="kb-retrieval-instruction" />
            </FormField>
          )}
          {(draft.rerank || draft.rewrite === 'rewrite') && (
            <FormField id="ret-query-model" label="Model alias" hint="The models-service chat alias both steps call. Empty uses the installation’s default.">
              <Input id="ret-query-model" className="w-60 bg-background font-mono text-sm" value={draft.queryModel} onChange={(e) => set({ queryModel: e.target.value.trim() })} placeholder="Installation default" />
            </FormField>
          )}
        </div>
      </SettingsSection>

      <div className="flex flex-wrap items-center justify-end gap-2">
        <PageSaveActions dirty={dirty} saving={update.isPending} invalid={invalid} onSave={save} onDiscard={() => setDraft(saved)} testId="kb-retrieval-save" />
      </div>
    </div>
  );
}

function NumberSlider({ id, label, hint, value, min, max, step, error, onChange }: { id: string; label: string; hint: string; value: number; min: number; max: number; step: number; error?: string; onChange: (v: number) => void }) {
  return (
    <FormField id={id} label={label} hint={hint} error={error}>
      <div className="flex items-center gap-3">
        <Slider className="max-w-80" value={[value]} min={min} max={max} step={step} onValueChange={([x]) => onChange(x)} aria-label={label} />
        <Input id={id} type="number" className="w-24 bg-background text-right tabular-nums" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Number(e.target.value))} aria-invalid={!!error} />
      </div>
    </FormField>
  );
}
