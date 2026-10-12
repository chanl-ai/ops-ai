'use client';

import * as React from 'react';
import { Eye, Pencil, Plus, X } from 'lucide-react';
import { toast } from 'sonner';

import { FormField } from '@/components/shared/form-field';
import { SettingsSection } from '@/components/shared/settings-section';
import { TagInput } from '@/components/shared/tag-input';
import { EDIT_CLASS, EditClassBadge, MarkdownPreview } from '@/components/skills/skill-meta';
import { AccessBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useSaveSkillDraft, useSkillOptions } from '@/hooks/skill-queries';
import { SKILL_LOADING_OPTIONS } from '@/components/skills/skill-loading';
import type { SkillDetail, SkillEditClass, SkillLoading } from '@/lib/types/skills';

interface Form {
  name: string;
  useWhen: string;
  loading: SkillLoading;
  instructions: string;
  toolIds: string[];
  knowledgeBases: string[];
  guardrails: string[];
}

const formOf = (sk: SkillDetail): Form => ({ name: sk.content.name, useWhen: sk.content.useWhen, loading: sk.content.loading, instructions: sk.content.instructions, toolIds: sk.content.tools.map((t) => t.toolId), knowledgeBases: sk.content.knowledgeBases, guardrails: sk.content.guardrails });
const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

/**
 * The newest version as a form. Saving edits the open draft, or opens a new draft on top of the published version;
 * nothing reaches an agent until a publisher approves it. The unsaved bar says which edit class the change is.
 */
export function InstructionsTab({ skill: sk }: { skill: SkillDetail }) {
  const save = useSaveSkillDraft(sk.id);
  const options = useSkillOptions();
  const saved = React.useMemo(() => formOf(sk), [sk]);
  const [form, setForm] = React.useState<Form>(saved);
  const [mode, setMode] = React.useState<'edit' | 'preview'>('edit');
  const [note, setNote] = React.useState('');
  const newest = sk.versions[0];
  const locked = newest.state === 'in_review' ? `v${newest.version} is waiting in Reviews.` : sk.status === 'deprecated' ? 'The skill is deprecated. Duplicate it to change it.' : undefined;
  const changed = {
    wording: form.name !== saved.name || form.useWhen !== saved.useWhen || form.loading !== saved.loading || form.instructions !== saved.instructions,
    scope: !same(form.toolIds, saved.toolIds) || !same(form.knowledgeBases, saved.knowledgeBases) || !same(form.guardrails, saved.guardrails),
  };
  const dirty = changed.wording || changed.scope;
  const editClass: SkillEditClass = changed.scope ? 're_approval' : 're_test';
  const limit = options.data?.limits.useWhenMaxChars ?? 1024;
  const errors = { name: form.name.trim() ? undefined : 'Name the skill.', useWhen: !form.useWhen.trim() && form.loading !== 'always' ? 'Say when the skill should be used.' : form.useWhen.length > limit ? `Keep it under ${limit} characters.` : undefined };
  const tools = options.data?.tools ?? [];
  const toolOf = (id: string) => tools.find((t) => t.toolId === id) ?? sk.content.tools.find((t) => t.toolId === id);
  const target = newest.state === 'draft' ? `draft v${newest.version}` : `draft v${newest.version + 1}`;

  // The tab remounts once the saved version arrives, so the toast follows the awaited result rather than mutate callbacks.
  const submit = async () => {
    try {
      const d = await save.mutateAsync({ name: form.name, useWhen: form.useWhen, loading: form.loading, instructions: form.instructions, toolIds: form.toolIds, knowledgeBases: form.knowledgeBases, guardrails: form.guardrails, note: note.trim() || undefined, baseVersion: newest.version });
      toast.success(`Saved draft v${d.versions[0].version}`, { description: `${EDIT_CLASS[d.versions[0].editClass].hint} Run the tests before requesting review.` });
    } catch (e) {
      toast.error('Couldn’t save the draft', { description: (e as Error).message });
    }
  };

  return (
    <div className="flex flex-col gap-4" data-testid="skill-instructions-tab">
      {locked && <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">{locked} Fields are read-only.</p>}
      <SettingsSection title="Name and loading" description="On match: the model loads the skill when a message fits the use-when line; keep it specific. Always on: the skill is added to every turn of every agent that pins it, after the agent’s own instructions, for shared wording such as a disclosure or tone guide.">
        <div className="flex flex-col gap-4">
          <FormField id="si-name" label="Name" error={errors.name}>
            <Input id="si-name" value={form.name} disabled={!!locked} onChange={(e) => setForm({ ...form, name: e.target.value })} className="bg-card" />
          </FormField>
          <FormField id="si-loading" label="Loading">
            <Select value={form.loading} disabled={!!locked} onValueChange={(v) => setForm({ ...form, loading: v as SkillLoading })}>
              <SelectTrigger id="si-loading" className="w-48 bg-card" data-testid="skill-loading-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SKILL_LOADING_OPTIONS.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {form.loading === 'on_match' && (
            <FormField id="si-usewhen" label="Use when" error={errors.useWhen} hint={`${form.useWhen.length} of ${limit} characters.`}>
              <Textarea id="si-usewhen" value={form.useWhen} disabled={!!locked} onChange={(e) => setForm({ ...form, useWhen: e.target.value })} className="min-h-16 bg-card" />
            </FormField>
          )}
        </div>
      </SettingsSection>

      <SettingsSection title="Instructions" description="Markdown with four sections: Steps, Rules, Examples and Output format.">
        <div className="flex flex-col gap-2">
          <ToggleGroup type="single" value={mode} onValueChange={(v) => v && setMode(v as 'edit' | 'preview')} variant="outline" size="sm" className="self-start" aria-label="Editor mode">
            <ToggleGroupItem value="edit" aria-label="Edit">
              <Pencil className="size-3.5" /> Edit
            </ToggleGroupItem>
            <ToggleGroupItem value="preview" aria-label="Preview" data-testid="instructions-preview-toggle">
              <Eye className="size-3.5" /> Preview
            </ToggleGroupItem>
          </ToggleGroup>
          {mode === 'edit' ? (
            <Textarea value={form.instructions} disabled={!!locked} onChange={(e) => setForm({ ...form, instructions: e.target.value })} className="min-h-96 bg-card font-mono text-xs leading-relaxed" aria-label="Instructions" data-testid="instructions-editor" />
          ) : (
            <div className="min-h-96 rounded-md border bg-card p-4" data-testid="instructions-preview">
              <MarkdownPreview text={form.instructions} />
            </div>
          )}
        </div>
      </SettingsSection>

      <SettingsSection title="Tools, knowledge and guardrails" description="Changing any of these needs two approvers. The agent must already hold each tool and knowledge base.">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">Tools</span>
            <div className="flex flex-col divide-y rounded-md border bg-card">
              {form.toolIds.length ? (
                form.toolIds.map((id) => {
                  const t = toolOf(id);
                  return (
                    <div key={id} className="flex items-center gap-2 px-3 py-1.5">
                      <code className="flex-1 truncate font-mono text-xs">{t?.name ?? id}</code>
                      <span className="text-xs text-muted-foreground">{t?.module}</span>
                      {t && <AccessBadge access={t.access} />}
                      <Button variant="ghost" size="icon" className="size-7" disabled={!!locked} aria-label={`Remove ${t?.name ?? id}`} onClick={() => setForm({ ...form, toolIds: form.toolIds.filter((x) => x !== id) })}>
                        <X className="size-3.5" />
                      </Button>
                    </div>
                  );
                })
              ) : (
                <p className="px-3 py-2 text-sm text-muted-foreground">No tools. The skill answers from its instructions and knowledge only.</p>
              )}
            </div>
            <Select value="" onValueChange={(v) => setForm({ ...form, toolIds: [...form.toolIds, v] })} disabled={!!locked}>
              <SelectTrigger className="w-72 bg-card" aria-label="Add a tool">
                <Plus className="size-3.5" /> <SelectValue placeholder="Add a tool operation" />
              </SelectTrigger>
              <SelectContent>
                {tools
                  .filter((t) => !form.toolIds.includes(t.toolId))
                  .map((t) => (
                    <SelectItem key={t.toolId} value={t.toolId}>
                      <span className="font-mono text-xs">{t.name}</span> <span className="text-xs text-muted-foreground">· {t.module}</span>
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">Knowledge bases</span>
            <div className="flex flex-wrap gap-1.5">
              {(options.data?.knowledgeBases ?? sk.content.knowledgeBases).map((k) => {
                const on = form.knowledgeBases.includes(k);
                return (
                  <button key={k} type="button" disabled={!!locked} aria-pressed={on} onClick={() => setForm({ ...form, knowledgeBases: on ? form.knowledgeBases.filter((x) => x !== k) : [...form.knowledgeBases, k] })} className="rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-60">
                    <Badge variant={on ? 'default' : 'outline'} className="cursor-pointer font-normal">
                      {k}
                    </Badge>
                  </button>
                );
              })}
            </div>
          </div>
          <FormField id="si-guardrails" label="Guardrails" hint="Added to the turn while the skill is loaded. They only restrict; they never widen access.">
            <TagInput id="si-guardrails" value={form.guardrails} onChange={(g) => setForm({ ...form, guardrails: g })} disabled={!!locked} placeholder="Add a guardrail and press Enter" className="bg-card" />
          </FormField>
        </div>
      </SettingsSection>

      {dirty && !locked && (
        <div data-unsaved-bar className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-3 rounded-lg border border-primary/30 bg-background/95 px-4 py-3 shadow-[0_-6px_16px_-10px_rgb(0_0_0/0.25)] backdrop-blur" role="status" data-testid="skill-unsaved-bar">
          <EditClassBadge editClass={editClass} />
          <span className="min-w-0 flex-1 text-sm">{EDIT_CLASS[editClass].hint}</span>
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Add the joint account rule" className="h-8 w-56" aria-label="Version note" />
          <Button variant="ghost" size="sm" onClick={() => setForm(saved)}>
            Discard
          </Button>
          <Button size="sm" onClick={submit} disabled={!!errors.name || !!errors.useWhen || save.isPending} data-testid="save-skill-draft">
            Save {target}
          </Button>
        </div>
      )}
    </div>
  );
}
