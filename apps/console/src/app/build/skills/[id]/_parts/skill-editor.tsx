'use client';

import * as React from 'react';
import { CircleAlert, Eye, Pencil, RefreshCw, TriangleAlert, Users, X } from 'lucide-react';
import { toast } from 'sonner';

import { AddMenu } from '@/components/shared/add-menu';
import { FormField } from '@/components/shared/form-field';
import { LeaveGuard } from '@/components/shared/leave-guard';
import { SettingsSection } from '@/components/shared/settings-section';
import { TagInput } from '@/components/shared/tag-input';
import { SkillDocumentEditor } from '@/components/skills/skill-document-editor';
import { SkillInputsSection } from '@/components/skills/skill-inputs-section';
import { EDIT_CLASS, EditClassBadge, MarkdownPreview } from '@/components/skills/skill-meta';
import { inText, refusedSave } from '@/components/skills/skill-problems';
import { SkillResultsSection, type SkillEndingValue } from '@/components/skills/skill-results-section';
import { SkillWhenSection, type SkillWhen, type SkillWhenHandle } from '@/components/skills/skill-when-section';
import { AccessBadge } from '@/components/status-badges';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useSaveSkillDraft, useSkill, useSkillOptions } from '@/hooks/skill-queries';
import { SKILL_LOADING_OPTIONS } from '@/components/skills/skill-loading';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { PageSaveActions } from '@/components/shared/page-save-actions';
import type { InstructionDocumentHandle, StepValue } from '@/components/shared/instruction-document';
import { plural } from '@/lib/format';
import type { PublishBlocker } from '@/lib/types/references';
import type { SkillDetail, SkillEditClass, SkillInputField, SkillLoading, SkillPartContent } from '@/lib/types/skills';

import { PartsSection, partsError } from './parts-section';

interface Form {
  name: string;
  when: SkillWhen;
  loading: SkillLoading;
  instructions: string;
  toolIds: string[];
  knowledgeBases: string[];
  guardrails: string[];
  refusal: string;
  parts: SkillPartContent[];
  steps: StepValue[];
  ending: SkillEndingValue;
  inputs: SkillInputField[];
}

const formOf = (sk: SkillDetail): Form => ({ name: sk.content.name, when: { useWhen: sk.content.useWhen, notWhen: sk.content.notWhen ?? '' }, loading: sk.content.loading, instructions: sk.content.instructions, toolIds: sk.content.tools.map((t) => t.toolId), knowledgeBases: sk.content.knowledgeBases, guardrails: sk.content.guardrails, refusal: sk.content.refusal ?? '', parts: sk.content.parts ?? [], steps: sk.content.steps ?? [], ending: { exit: sk.content.exit ?? {}, returns: sk.content.returns ?? [], success: sk.content.success ?? [] }, inputs: sk.content.inputs ?? [] });
const NONE: PublishBlocker[] = [];
const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

/**
 * The newest version as a form: when to use the skill, its notes and steps as one document, then its settings. Saving
 * edits the open draft, or opens a new draft on top of the published version; nothing reaches an agent until a
 * publisher approves it. The unsaved bar says which edit class the change is. A person who may not change the team's
 * skills (`canEdit` false) reads the same form with every field off and no save.
 */
export function SkillEditor({ skill: sk, canEdit, onDirtyChange }: { skill: SkillDetail; canEdit: boolean; onDirtyChange?: (dirty: boolean) => void }) {
  const save = useSaveSkillDraft(sk.id);
  const current = useSkill(sk.id);
  const [noting, setNoting] = React.useState(false);
  const options = useSkillOptions();
  const saved = React.useMemo(() => formOf(sk), [sk]);
  const [form, setForm] = React.useState<Form>(saved);
  const [mode, setMode] = React.useState<'edit' | 'preview'>('edit');
  const [note, setNote] = React.useState('');
  const [endingValid, setEndingValid] = React.useState(true);
  const [whenValid, setWhenValid] = React.useState(true);
  const [inputsValid, setInputsValid] = React.useState(true);
  // The when and endings forms keep their own field state, so a discard remounts them on the saved values.
  const [discards, setDiscards] = React.useState(0);
  const setEnding = React.useCallback((ending: SkillEndingValue) => setForm((f) => ({ ...f, ending })), []);
  const setWhen = React.useCallback((when: SkillWhen) => setForm((f) => ({ ...f, when })), []);
  const setInputs = React.useCallback((inputs: SkillInputField[]) => setForm((f) => ({ ...f, inputs })), []);
  const whenForm = React.useRef<SkillWhenHandle>(null);
  const stepsDoc = React.useRef<InstructionDocumentHandle>(null);
  // A save refused because a newer version exists: what the service said. Cleared by Reload.
  const [stale, setStale] = React.useState<string | null>(null);
  // A save that did not go through for any other reason: what the service said, kept with a Retry until a save works.
  const [failed, setFailed] = React.useState<string | null>(null);
  // A save refused for one step, shown on that step until the steps change.
  const [refused, setRefused] = React.useState<PublishBlocker | null>(null);
  // A skill has steps or parts, never both: one with parts keeps its Markdown body.
  const stepped = form.parts.length === 0;
  const newest = sk.versions[0];
  const locked = newest.state === 'in_review' ? `v${newest.version} is waiting in Reviews.` : sk.status === 'deprecated' ? 'The skill is deprecated. Duplicate it to change it.' : undefined;
  // The document editor and the save bar sit outside what a disabled fieldset reaches, so they read this.
  const readOnly = !!locked || !canEdit;
  const changed = {
    wording: form.name !== saved.name || form.when.useWhen !== saved.when.useWhen || form.when.notWhen.trim() !== saved.when.notWhen.trim() || form.loading !== saved.loading || form.instructions !== saved.instructions || JSON.stringify([form.parts, form.steps, form.ending, form.inputs]) !== JSON.stringify([saved.parts, saved.steps, saved.ending, saved.inputs]),
    scope: !same(form.toolIds, saved.toolIds) || !same(form.knowledgeBases, saved.knowledgeBases) || !same(form.guardrails, saved.guardrails) || form.refusal.trim() !== saved.refusal.trim(),
  };
  const dirty = changed.wording || changed.scope;
  // The page holds back what would redraw this form (a file added, a version restored) while there is unsaved text.
  React.useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  const editClass: SkillEditClass = changed.scope ? 're_approval' : 're_test';
  const limit = options.data?.limits.useWhenMaxChars ?? 1024;
  const errors = { name: form.name.trim() ? undefined : 'Name the skill.', parts: partsError(form.parts) };
  const found = React.useMemo(() => (newest.state === 'draft' ? inText(sk.publishCheck.problems ?? NONE) : NONE), [newest.state, sk.publishCheck.problems]);
  const problems = React.useMemo(() => (refused ? [...found, refused] : found), [found, refused]);
  // A missing list from an older service is none.
  const warnings = newest.state === 'draft' ? sk.publishCheck.warnings : undefined;
  const discard = () => (setForm(saved), setEndingValid(true), setWhenValid(true), setInputsValid(true), setRefused(null), setFailed(null), setDiscards((n) => n + 1));
  const tools = options.data?.tools ?? [];
  const toolOf = (id: string) => tools.find((t) => t.toolId === id) ?? sk.content.tools.find((t) => t.toolId === id);
  const target = newest.state === 'draft' ? `draft v${newest.version}` : `draft v${newest.version + 1}`;

  // The tab remounts once the saved version arrives, so the toast follows the awaited result rather than mutate callbacks.
  const submit = async () => {
    setFailed(null);
    try {
      const d = await save.mutateAsync({ name: form.name, useWhen: form.when.useWhen, loading: form.loading, instructions: form.instructions, toolIds: form.toolIds, knowledgeBases: form.knowledgeBases, guardrails: form.guardrails, refusal: form.refusal.trim(), parts: form.parts, ...(stepped ? { inputs: form.inputs, steps: form.steps, notWhen: form.when.notWhen.trim(), exit: form.ending.exit, returns: form.ending.returns, success: form.ending.success } : {}), note: note.trim() || undefined, baseVersion: newest.version });
      toast.success(`Saved draft v${d.versions[0].version}`, { description: `${EDIT_CLASS[d.versions[0].editClass].hint} Run the tests before requesting review.` });
    } catch (e) {
      // In review and deprecated are 409 as well; only a newer version offers a reload.
      if ((e as { code?: string }).code === 'stale_base') return setStale((e as Error).message);
      const onStep = refusedSave(e);
      if (onStep?.position?.step) {
        setRefused(onStep);
        stepsDoc.current?.focus({ field: 'steps', step: onStep.position.step });
        return void toast.error('Couldn’t save the draft', { description: `Step ${onStep.position.step} needs a fix.` });
      }
      // The toast goes away; the page keeps saying so, with a way to try again, while the text is still unsaved.
      setFailed((e as Error).message);
      toast.error('Couldn’t save the draft', { description: (e as Error).message });
    }
  };
  // The page remounts this form when a newer version arrives; with nothing newer, the form goes back to what is saved.
  const reload = async () => {
    await current.refetch();
    setStale(null);
    discard();
  };
  const askNote = async () => {
    if (whenValid) return setNoting(true);
    await whenForm.current?.check();
  };

  return (
    <div className="flex flex-col gap-4" data-testid="skill-editor">
      <LeaveGuard unsaved={dirty && !readOnly} failed={!!failed} />
      {locked && <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">{locked} Fields are read-only.</p>}
      {stale && (
        <Alert data-testid="skill-stale-base">
          <Users />
          <AlertTitle>Someone else saved this skill</AlertTitle>
          <AlertDescription>
            <p>{stale} Reloading shows their version and drops the changes you have not saved; copy anything you want to keep first.</p>
            <Button variant="outline" size="sm" onClick={() => void reload()} disabled={current.isFetching} data-testid="skill-stale-reload">
              <RefreshCw className="size-3.5" /> Reload
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {failed && !stale && (
        <Alert data-testid="skill-save-failed">
          <CircleAlert />
          <AlertTitle>Your last change didn’t save</AlertTitle>
          <AlertDescription>
            <p>It is kept on this page. Check your connection, then retry.</p>
            <p className="text-xs">{failed}</p>
            <Button variant="outline" size="sm" onClick={() => void submit()} disabled={save.isPending} data-testid="skill-save-retry">
              <RefreshCw className="size-3.5" /> Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {problems.length > 0 && (
        <Alert data-testid="skill-publish-problems">
          <TriangleAlert />
          <AlertTitle>{found.length ? 'Can’t publish yet' : 'Couldn’t save'}</AlertTitle>
          <AlertDescription>
            <p>
              {plural(problems.length, 'problem')}. Fix {problems.length === 1 ? 'it' : 'them'} in the text and save again.
            </p>
            {problems.map((p, i) => (
              <p key={i} className="flex flex-wrap items-center gap-x-2" data-testid="skill-problem">
                <span>{p.message}</span>
                {p.position?.field === 'steps' && p.position.step && (
                  <Button variant="link" size="sm" className="h-auto p-0" onClick={() => stepsDoc.current?.focus({ field: 'steps', step: p.position!.step! })}>
                    Go to step {p.position.step}
                  </Button>
                )}
              </p>
            ))}
          </AlertDescription>
        </Alert>
      )}
      <SkillWhenSection key={`when-${discards}`} value={saved.when} onChange={setWhen} onValidity={setWhenValid} useWhenMax={limit} needsUseWhen={form.loading === 'on_match'} showNotWhen={stepped} notWhenProblem={problems.find((p) => p.position?.field === 'notWhen')?.message} disabled={readOnly} controls={whenForm} />
      {stepped ? (
        <SettingsSection title="Notes and steps" description="Notes hold for the whole skill. Steps run in order: each can name a tool, a check on what came back, and what happens when the check fails.">
          <SkillDocumentEditor skillId={sk.id} name={form.name} value={{ instructions: form.instructions, steps: form.steps }} onChange={(doc) => (setRefused(null), setForm((f) => ({ ...f, ...doc })))} readOnly={readOnly} problems={problems} warnings={warnings} controls={stepsDoc} />
        </SettingsSection>
      ) : (
        <SettingsSection title="Instructions" description="Markdown with four sections: Steps, Rules, Examples and Output format.">
          <div className="flex flex-col gap-2">
            <p className="rounded-md border bg-muted/40 px-3 py-2 text-sm text-muted-foreground" data-testid="skill-parts-or-steps">
              This skill is written in parts, so its steps are hidden. A skill has parts or numbered steps, not both. Remove every part to write steps again.
            </p>
            <ToggleGroup type="single" value={mode} onValueChange={(v) => v && setMode(v as 'edit' | 'preview')} variant="outline" size="sm" className="self-start" aria-label="Editor mode">
              <ToggleGroupItem value="edit" aria-label="Edit">
                <Pencil className="size-3.5" /> Edit
              </ToggleGroupItem>
              <ToggleGroupItem value="preview" aria-label="Preview" data-testid="instructions-preview-toggle">
                <Eye className="size-3.5" /> Preview
              </ToggleGroupItem>
            </ToggleGroup>
            {mode === 'edit' ? (
              <Textarea value={form.instructions} disabled={readOnly} onChange={(e) => setForm({ ...form, instructions: e.target.value })} className="min-h-96 bg-card font-mono text-xs leading-relaxed" aria-label="Instructions" data-testid="instructions-editor" />
            ) : (
              <div className="min-h-96 rounded-md border bg-card p-4" data-testid="instructions-preview">
                <MarkdownPreview text={form.instructions} />
              </div>
            )}
          </div>
        </SettingsSection>
      )}

      <PartsSection parts={form.parts} onChange={(parts) => setForm({ ...form, parts })} disabled={readOnly} />

      <SettingsSection title="Name and loading" description="On match: the model loads the skill when a message fits the use-when line; keep it specific. Always on: the skill is added to every turn of every agent that pins it, after the agent’s own instructions, for shared wording such as a disclosure or tone guide.">
        <div className="flex flex-col gap-4">
          <FormField id="si-name" label="Name" error={errors.name}>
            <Input id="si-name" value={form.name} disabled={readOnly} onChange={(e) => setForm({ ...form, name: e.target.value })} className="bg-card" />
          </FormField>
          <FormField id="si-loading" label="Loading">
            <Select value={form.loading} disabled={readOnly} onValueChange={(v) => setForm({ ...form, loading: v as SkillLoading })}>
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
        </div>
      </SettingsSection>


      <SettingsSection title="Tools, knowledge and guardrails" description="Changing any of these needs two reviewers. The agent must already hold each tool and knowledge base.">
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
                      <Button variant="ghost" size="icon" className="size-7" disabled={readOnly} aria-label={`Remove ${t?.name ?? id}`} onClick={() => setForm({ ...form, toolIds: form.toolIds.filter((x) => x !== id) })}>
                        <X className="size-3.5" />
                      </Button>
                    </div>
                  );
                })
              ) : (
                <p className="px-3 py-2 text-sm text-muted-foreground">No tools. The skill answers from its instructions and knowledge only.</p>
              )}
            </div>
            <AddMenu
              label="Add a tool operation"
              items={tools
                .filter((t) => !form.toolIds.includes(t.toolId))
                .map((t) => ({
                  value: t.toolId,
                  label: (
                    <>
                      <span className="font-mono text-xs">{t.name}</span> <span className="text-xs text-muted-foreground">· {t.module}</span>
                    </>
                  ),
                }))}
              onSelect={(v) => setForm({ ...form, toolIds: [...form.toolIds, v] })}
              disabled={readOnly}
              className="w-72"
            />
          </div>
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium">Knowledge bases</span>
            <div className="flex flex-wrap gap-1.5">
              {(options.data?.knowledgeBases ?? sk.content.knowledgeBases).map((k) => {
                const on = form.knowledgeBases.includes(k);
                return (
                  <button key={k} type="button" disabled={readOnly} aria-pressed={on} onClick={() => setForm({ ...form, knowledgeBases: on ? form.knowledgeBases.filter((x) => x !== k) : [...form.knowledgeBases, k] })} className="rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none disabled:opacity-60">
                    <Badge variant={on ? 'default' : 'outline'} className="cursor-pointer font-normal">
                      {k}
                    </Badge>
                  </button>
                );
              })}
            </div>
          </div>
          <FormField id="si-guardrails" label="Guardrails" hint="Added to the turn while the skill is loaded. They only restrict; they never widen access.">
            <TagInput id="si-guardrails" value={form.guardrails} onChange={(g) => setForm({ ...form, guardrails: g })} disabled={readOnly} placeholder="Add a guardrail and press Enter" className="bg-card" />
          </FormField>
          <FormField id="si-refusal" label="When a guardrail refuses, say" hint="What the person reads instead of the answer. Offer the next step the skill can take.">
            <Textarea id="si-refusal" rows={2} value={form.refusal} onChange={(e) => setForm({ ...form, refusal: e.target.value })} disabled={readOnly || !form.guardrails.length} placeholder="e.g. I can't promise a deferral, but I can start a hardship request now." className="bg-card" data-testid="skill-refusal" />
          </FormField>
        </div>
      </SettingsSection>

      {/* A skill with parts takes its inputs on each part. */}
      {stepped && <SkillInputsSection key={`inputs-${discards}`} value={saved.inputs} onChange={setInputs} onValidity={setInputsValid} disabled={readOnly} />}
      {stepped && <SkillResultsSection key={discards} value={saved.ending} onChange={setEnding} onValidity={setEndingValid} disabled={readOnly} />}

      {!readOnly && (
        <PageSaveActions
          dirty={dirty}
          saving={save.isPending}
          onDiscard={discard}
          save={
            // Saving asks for a version note and says what this kind of edit needs before it goes live.
            <Popover open={noting} onOpenChange={(open) => (open ? void askNote() : setNoting(false))}>
              <PopoverTrigger asChild>
                <Button size="sm" disabled={!dirty || !!errors.name || !!errors.parts || !endingValid || !inputsValid || save.isPending} data-testid="save-skill-draft">
                  Save {target}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="flex w-80 flex-col gap-3">
                <div className="flex items-start gap-2">
                  <EditClassBadge editClass={editClass} />
                  <p className="text-sm text-muted-foreground">{errors.parts ?? EDIT_CLASS[editClass].hint}</p>
                </div>
                <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Add the joint account rule" aria-label="Version note" />
                <Button size="sm" className="self-end" onClick={() => (setNoting(false), submit())} disabled={save.isPending} data-testid="save-skill-draft-confirm">
                  Save {target}
                </Button>
              </PopoverContent>
            </Popover>
          }
        />
      )}
    </div>
  );
}
