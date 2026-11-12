'use client';

import * as React from 'react';
import { ArrowDown, ArrowUp, ChevronDown, Plus, Trash2, X } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { SettingsSection } from '@/components/shared/settings-section';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import type { SkillInputField, SkillPartContent } from '@/lib/types/skills';

export const MAX_PARTS = 8;
const TOKEN_BUDGET = 6000;

const slugOf = (name: string) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64);
const tokensOf = (text: string) => Math.max(1, Math.ceil(text.length / 4));
const inputCount = (n: number) => (n === 0 ? 'No inputs' : n === 1 ? '1 input' : `${n} inputs`);

/** The first problem with the parts, for the unsaved bar; undefined when they can be saved. */
export function partsError(parts: SkillPartContent[]): string | undefined {
  const slugs = new Set<string>();
  for (const [i, p] of parts.entries()) {
    const where = p.name.trim() || `Part ${i + 1}`;
    if (!p.name.trim()) return `Part ${i + 1} needs a name.`;
    if (!p.instructions.trim()) return `${where} needs instructions.`;
    if (!p.slug) return `${where} needs a name with letters or digits.`;
    if (slugs.has(p.slug)) return `Two parts are called ${p.slug}; rename one.`;
    slugs.add(p.slug);
    if (p.inputs.some((f) => !/^[a-z][a-z0-9_]{0,63}$/.test(f.name))) return `${where}: an input name is lowercase letters, digits and _.`;
  }
  return undefined;
}

/**
 * A skill's parts: each picked on its own from the chat's / menu and loaded with the shared overview (the
 * instructions above). One row open at a time; arrows reorder, so it works by keyboard and touch.
 */
export function PartsSection({ parts, onChange, disabled }: { parts: SkillPartContent[]; onChange: (parts: SkillPartContent[]) => void; disabled: boolean }) {
  const [open, setOpen] = React.useState<number | null>(null);
  const put = (i: number, patch: Partial<SkillPartContent>) => onChange(parts.map((p, n) => (n === i ? { ...p, ...patch } : p)));
  const move = (i: number, by: -1 | 1) => {
    const next = [...parts];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    onChange(next);
    setOpen(open === i ? i + by : open === i + by ? i : open);
  };
  const add = () => {
    onChange([...parts, { slug: '', name: '', useWhen: '', instructions: '', inputs: [], toolIds: [] }]);
    setOpen(parts.length);
  };
  const remove = (i: number) => {
    onChange(parts.filter((_, n) => n !== i));
    setOpen(null);
  };
  const putInput = (i: number, k: number, patch: Partial<SkillInputField>) => put(i, { inputs: parts[i].inputs.map((f, n) => (n === k ? { ...f, ...patch } : f)) });

  return (
    <SettingsSection
      title="Parts"
      description={`Each part is picked on its own from the / menu and loads with the instructions above as its shared overview. ${parts.length} of ${MAX_PARTS} parts.`}
    >
      <div className="flex flex-col gap-3">
      {parts.length === 0 ? (
        <p className="text-sm text-muted-foreground">No parts. The / menu offers the whole skill. Add parts when it does several separate jobs.</p>
      ) : (
        <div className="flex flex-col gap-2" data-testid="skill-parts">
          {parts.map((p, i) => {
            const tokens = tokensOf(p.instructions);
            return (
              <Collapsible key={i} open={open === i} onOpenChange={(o) => setOpen(o ? i : null)} className="rounded-md border bg-card">
                <div className="flex flex-wrap items-center gap-2 px-3 py-2">
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs tabular-nums">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{p.name || 'New part'}</div>
                    <div className="truncate text-xs text-muted-foreground">{p.useWhen || 'No use-when line yet.'}</div>
                  </div>
                  <Badge variant="secondary" className="font-normal">
                    {inputCount(p.inputs.length)}
                  </Badge>
                  <Badge variant="outline" className="font-normal tabular-nums">
                    {tokens.toLocaleString('en-CA')} / {(p.budget ?? TOKEN_BUDGET).toLocaleString('en-CA')} tokens
                  </Badge>
                  <Button variant="ghost" size="icon" className="size-8" disabled={disabled || i === 0} onClick={() => move(i, -1)} aria-label={`Move ${p.name || 'part'} up`}>
                    <ArrowUp className="size-4" />
                  </Button>
                  <Button variant="ghost" size="icon" className="size-8" disabled={disabled || i === parts.length - 1} onClick={() => move(i, 1)} aria-label={`Move ${p.name || 'part'} down`}>
                    <ArrowDown className="size-4" />
                  </Button>
                  <Button variant="ghost" size="icon" className="size-8" disabled={disabled} onClick={() => remove(i)} aria-label={`Remove ${p.name || 'part'}`}>
                    <Trash2 className="size-4" />
                  </Button>
                  <CollapsibleTrigger asChild>
                    <Button variant="ghost" size="icon" className="size-8" aria-label={open === i ? 'Close' : `Edit ${p.name || 'part'}`}>
                      <ChevronDown className={open === i ? 'size-4 rotate-180' : 'size-4'} />
                    </Button>
                  </CollapsibleTrigger>
                </div>
                <CollapsibleContent className="flex flex-col gap-4 border-t p-3">
                  <FormField id={`part-${i}-name`} label="Name" hint={p.slug ? `Picked as ${p.slug}.` : undefined}>
                    <Input id={`part-${i}-name`} value={p.name} disabled={disabled} onChange={(e) => put(i, { name: e.target.value, slug: slugOf(e.target.value) })} className="bg-card" />
                  </FormField>
                  <FormField id={`part-${i}-use`} label="Use when">
                    <Input id={`part-${i}-use`} value={p.useWhen} disabled={disabled} onChange={(e) => put(i, { useWhen: e.target.value })} className="bg-card" />
                  </FormField>
                  <FormField id={`part-${i}-steps`} label="Instructions">
                    <Textarea id={`part-${i}-steps`} value={p.instructions} disabled={disabled} onChange={(e) => put(i, { instructions: e.target.value })} className="min-h-32 bg-card font-mono text-xs" />
                  </FormField>
                  <FormField id={`part-${i}-budget`} label="Token budget" hint={`At most ${TOKEN_BUDGET.toLocaleString('en-CA')}; empty takes the reply's whole skill budget.`}>
                    <Input
                      id={`part-${i}-budget`}
                      type="number"
                      min={1}
                      max={TOKEN_BUDGET}
                      value={p.budget ?? ''}
                      disabled={disabled}
                      onChange={(e) => put(i, { budget: e.target.value ? Math.min(TOKEN_BUDGET, Math.max(1, Number(e.target.value))) : undefined })}
                      className="w-32 bg-card tabular-nums"
                    />
                  </FormField>
                  <div className="flex flex-col gap-2">
                    <span className="text-sm font-medium">Inputs</span>
                    {p.inputs.map((f, k) => (
                      <div key={k} className="flex flex-wrap items-center gap-2">
                        <Input value={f.name} disabled={disabled} onChange={(e) => putInput(i, k, { name: e.target.value })} placeholder="client" aria-label="Input name" className="w-40 bg-card font-mono text-xs" />
                        <Input value={f.description} disabled={disabled} onChange={(e) => putInput(i, k, { description: e.target.value })} placeholder="What to type" aria-label="Input description" className="min-w-40 flex-1 bg-card" />
                        <div className="flex items-center gap-2">
                          <Switch id={`part-${i}-in-${k}`} checked={f.required} disabled={disabled} onCheckedChange={(v) => putInput(i, k, { required: v })} />
                          <Label htmlFor={`part-${i}-in-${k}`}>Required</Label>
                        </div>
                        <Button variant="ghost" size="icon" className="size-8" disabled={disabled} onClick={() => put(i, { inputs: p.inputs.filter((_, n) => n !== k) })} aria-label={`Remove input ${f.name}`}>
                          <X className="size-4" />
                        </Button>
                      </div>
                    ))}
                    <Button variant="outline" size="sm" className="self-start" disabled={disabled || p.inputs.length >= 20} onClick={() => put(i, { inputs: [...p.inputs, { name: '', type: 'string', description: '', required: false }] })}>
                      <Plus className="size-4" /> Add an input
                    </Button>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            );
          })}
        </div>
      )}
      <Button variant="outline" size="sm" className="self-start" onClick={add} disabled={disabled || parts.length >= MAX_PARTS} data-testid="add-skill-part">
        <Plus className="size-4" /> Add a part
      </Button>
      </div>
    </SettingsSection>
  );
}
