'use client';

import * as React from 'react';
import { AlertTriangle, FlaskConical, Pencil, Search, Sparkles, UserCheck } from 'lucide-react';

import { initialSpec, PromptGeneratorDialog } from '@/components/prompts/prompt-generator-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Stepper } from '@/components/shared/stepper';
import { KeyValues } from '@/components/shared/surface';
import { TagInput } from '@/components/shared/tag-input';
import { AccessBadge } from '@/components/status-badges';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import type { PromptGeneratorBackend } from '@/hooks/prompt-queries';
import type { Lookups } from '@/lib/api';
import { plural } from '@/lib/format';
import type { AgentGuardrails, ModelAlias, Tool } from '@/lib/types/domain';
import type { SkillCandidates, SkillCandidateScope } from '@/lib/types/skills';
import type { AgentTemplate, AgentTemplateDetail, CreateFromTemplateInput, SkillPinInput } from '@/lib/types/templates';
import { cn } from '@/lib/utils';

import { CATEGORY_ORDER, TemplateCard, TemplatePreview } from './template-meta';
import { modelHint, ModelSelect } from './model-select';
import { WorkflowToolFacts } from './workflow-tool-facts';
import { pinnableVersion, pinProblem, TemplateSkillsStep } from './template-skills-step';

const STEPS = ['Choose a template', 'Configure', 'Skills', 'Instructions', 'Guardrails', 'Review'] as const;
const UNSURE: Record<AgentGuardrails['whenUnsure'], string> = { handoff: 'Hand to a person', ask: 'Ask the customer to clarify', decline: 'Decline and explain why' };

interface Config {
  name: string;
  owner: string;
  model: string;
  collections: string[];
  toolIds: string[];
  instructions: string;
  guardrails: AgentGuardrails;
  includeTests: boolean;
  skills: SkillPinInput[];
  /** Suggestions already preselected (or left out by the person); each is preselected once, when it first fits. */
  skillsSeeded: string[];
}

/**
 * New agent from a template, in six steps. The template fills every field; Configure only offers the knowledge
 * bases that exist and the tools the current team may grant, and says what the template expected but cannot
 * have. The agent is created as a draft at version 1 with the template's starter tests in its evals.
 */
export function TemplateWizard({
  open,
  onOpenChange,
  templates,
  templatesLoading,
  templatesError,
  onRetryTemplates,
  search,
  onSearchChange,
  templateId,
  onTemplateChange,
  detail,
  detailLoading,
  startAtConfigure,
  lookups,
  models,
  defaultOwner,
  tools,
  generator,
  skillCandidates,
  onSkillScopeChange,
  onCreate,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  templates: AgentTemplate[];
  templatesLoading: boolean;
  templatesError: boolean;
  onRetryTemplates: () => void;
  search: string;
  onSearchChange: (s: string) => void;
  templateId: string | null;
  onTemplateChange: (id: string) => void;
  detail?: AgentTemplateDetail;
  detailLoading: boolean;
  /** Opened from "Use template": the template is chosen, so start at Configure. */
  startAtConfigure: boolean;
  lookups?: Lookups;
  /** The model aliases publish accepts (GET /v1/model-aliases). */
  models: ModelAlias[];
  defaultOwner?: string;
  /** Tools the current team may grant. */
  tools: Tool[];
  generator: PromptGeneratorBackend;
  /** Published skills an agent with the wizard's owner, tools and knowledge bases could pin. */
  skillCandidates: { data?: SkillCandidates; loading: boolean; error: boolean; onRetry: () => void };
  /** The page fetches candidates for this scope; null while there is nothing to scope. */
  onSkillScopeChange: (scope: SkillCandidateScope | null) => void;
  onCreate: (input: CreateFromTemplateInput) => Promise<unknown>;
  isPending: boolean;
}) {
  const [step, setStep] = React.useState(1);
  const [cfg, setCfg] = React.useState<Config | null>(null);
  const [initFor, setInitFor] = React.useState<string | null>(null);
  const [touched, setTouched] = React.useState(false);
  const [serverError, setServerError] = React.useState<{ step: number; field?: 'name'; message: string } | null>(null);
  const [genOpen, setGenOpen] = React.useState(false);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    setStep(startAtConfigure && templateId ? 2 : 1);
    setInitFor(null);
    setCfg(null);
    setTouched(false);
    setServerError(null);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);

  // A new template choice resets Configure to that template's defaults; going back and forth keeps edits.
  const key = detail ? `${detail.id}@${detail.version}` : null;
  React.useEffect(() => {
    if (!open || !detail || !key || key === initFor || detail.id !== templateId) return;
    const kbs = lookups?.collections ?? [];
    setCfg({
      name: '',
      owner: defaultOwner ?? lookups?.owners[0] ?? '',
      // The template's tested model when publish accepts it, else the first alias that it does.
      model: models.some((m) => m.name === detail.model) ? detail.model : (models[0]?.name ?? ''),
      collections: detail.expectedKnowledge.filter((k) => kbs.includes(k)),
      toolIds: tools.filter((t) => detail.expectedTools.some((x) => x.name === t.name)).map((t) => t.id),
      instructions: detail.instructions,
      guardrails: structuredClone(detail.guardrails),
      includeTests: detail.starterTests.length > 0,
      skills: [],
      skillsSeeded: [],
    });
    setInitFor(key);
  }, [open, detail, key, initFor, templateId, lookups, models, defaultOwner, tools]);

  const scopeKey = cfg ? JSON.stringify([cfg.owner, cfg.toolIds, cfg.collections]) : null;
  React.useEffect(() => {
    onSkillScopeChange(open && cfg?.owner ? { ownerTeam: cfg.owner, toolIds: cfg.toolIds, knowledgeBases: cfg.collections } : null);
  }, [open, scopeKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const candidates = skillCandidates.data;
  React.useEffect(() => {
    if (step !== 3 || !cfg || !candidates || skillCandidates.loading || !detail) return;
    const picks = detail.suggestedSkills.flatMap((sg) => {
      const c = cfg.skillsSeeded.includes(sg.skillId) ? undefined : candidates.attachable.find((x) => x.skillId === sg.skillId);
      const v = c && pinnableVersion(c);
      return v === undefined ? [] : [{ skillId: sg.skillId, version: v }];
    });
    if (!picks.length) return;
    setCfg((c) => (c ? { ...c, skills: [...c.skills, ...picks.filter((p) => !c.skills.some((x) => x.skillId === p.skillId))].slice(0, candidates.limits.maxAttached), skillsSeeded: [...c.skillsSeeded, ...picks.map((p) => p.skillId)] } : c));
  }, [step, cfg, candidates, skillCandidates.loading, detail]);

  const ready = !!cfg && !!detail && detail.id === templateId;
  const set = <K extends keyof Config>(k: K, v: Config[K]) => setCfg((c) => (c ? { ...c, [k]: v } : c));
  const errors = {
    template: templateId ? undefined : 'Choose a template to continue.',
    name: !cfg || cfg.name.trim().length < 2 || cfg.name.length > 80 ? 'Name the agent in 2 to 80 characters, e.g. Hardship Reply Drafter.' : serverError?.field === 'name' ? serverError.message : undefined,
    owner: cfg?.owner ? undefined : 'Choose the team that owns this agent.',
    model: cfg?.model ? undefined : 'Choose a model.',
    instructions: (cfg?.instructions.trim().length ?? 0) < 20 ? 'Write the instructions, or generate them with the prompt builder.' : undefined,
    skills: !cfg?.skills.length ? undefined : !candidates || skillCandidates.loading ? 'Loading skills…' : cfg.skills.map((p) => pinProblem(p, candidates, Object.fromEntries((detail?.suggestedSkills ?? []).map((x) => [x.skillId, x.name])))).find(Boolean),
  };
  const STEP_FIELDS: Record<number, (keyof typeof errors)[]> = { 1: ['template'], 2: ['name', 'owner', 'model'], 3: ['skills'], 4: ['instructions'], 5: [], 6: [] };
  const err = (k: keyof typeof errors) => (touched || (k === 'name' && serverError?.field === 'name') ? errors[k] : undefined);
  const stepValid = STEP_FIELDS[step].every((k) => !errors[k]) && (step === 1 || ready);
  const next = () => {
    if (!stepValid) return setTouched(true);
    setTouched(false);
    setStep(step + 1);
  };

  const granted = tools.filter((t) => cfg?.toolIds.includes(t.id));
  const missingKb = detail?.missingKnowledge ?? [];
  const unavailable = detail?.unavailableTools ?? [];
  const groups = CATEGORY_ORDER.filter((c) => templates.some((t) => t.category === c));
  const create = async () => {
    if (!cfg || !detail) return;
    setServerError(null);
    try {
      await onCreate({
        templateId: detail.id,
        templateVersion: detail.version,
        name: cfg.name.trim(),
        owner: cfg.owner,
        model: cfg.model,
        collections: cfg.collections,
        toolIds: cfg.toolIds,
        instructions: cfg.instructions,
        guardrails: cfg.guardrails,
        includeStarterTests: cfg.includeTests,
        skills: cfg.skills,
      });
      onOpenChange(false);
    } catch (e) {
      const message = (e as Error).message;
      if (/handle/.test(message)) {
        setServerError({ step: 2, field: 'name', message: `${message} Choose another name.` });
        setStep(2);
      } else setServerError({ step: 6, message });
    }
  };

  return (
    <>
      <DialogShell
        open={open}
        onOpenChange={onOpenChange}
        size="xl"
        title={detail && step > 1 ? `New agent from ${detail.name}` : 'New agent'}
        description={`Step ${step} of ${STEPS.length} · ${STEPS[step - 1]}`}
        headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="template-stepper" />}
        bodyRef={bodyRef}
        bodyClassName="h-[32rem]"
        data-testid="template-wizard"
        footer={
          <div className="flex w-full items-center justify-between gap-2">
            <Button variant="ghost" onClick={() => (step === 1 ? onOpenChange(false) : setStep(step - 1))} disabled={isPending}>
              {step === 1 ? 'Cancel' : 'Back'}
            </Button>
            {step < STEPS.length ? (
              <Button onClick={next} disabled={step === 1 && !!templateId && detailLoading}>
                Next
              </Button>
            ) : (
              <LoadingButton isLoading={isPending} loadingText="Creating…" onClick={create} data-testid="create-from-template">
                Create as draft
              </LoadingButton>
            )}
          </div>
        }
      >
        {step === 1 && (
          <div className="grid h-full gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
            <div className="flex min-h-0 flex-col gap-3">
              <div className="relative">
                <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input value={search} onChange={(e) => onSearchChange(e.target.value)} placeholder="Search templates…" className="pl-8" aria-label="Search templates" autoFocus />
              </div>
              {err('template') && <p className="text-xs text-destructive">{err('template')}</p>}
              <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                {templatesError ? (
                  <QueryError what="templates" onRetry={onRetryTemplates} />
                ) : templatesLoading ? (
                  <div className="grid gap-2 sm:grid-cols-2">
                    {Array.from({ length: 6 }, (_, i) => (
                      <Skeleton key={i} className="h-28" />
                    ))}
                  </div>
                ) : templates.length === 0 ? (
                  <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">{search ? 'No template matches that search. Try a different word, or close this and use New agent for a blank one.' : 'No templates are published yet. Ask the platform team to publish one.'}</p>
                ) : (
                  <div className="flex flex-col gap-4">
                    {groups.map((c) => (
                      <section key={c} aria-label={c}>
                        <h3 className="mb-1.5 text-xs font-medium text-muted-foreground">{c}</h3>
                        <div className="grid gap-2 sm:grid-cols-2">
                          {templates
                            .filter((t) => t.category === c)
                            .map((t) => (
                              <TemplateCard key={t.id} template={t} selected={t.id === templateId} onSelect={() => onTemplateChange(t.id)} />
                            ))}
                        </div>
                      </section>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <aside className="min-h-0 overflow-y-auto rounded-lg border p-3" aria-label="Template preview">
              {!templateId ? (
                <p className="text-sm text-muted-foreground">Choose a template to see what it does, what it expects and an example.</p>
              ) : detailLoading || !detail ? (
                <div className="flex flex-col gap-2">
                  <Skeleton className="h-5 w-40" />
                  <Skeleton className="h-16" />
                  <Skeleton className="h-24" />
                </div>
              ) : (
                <TemplatePreview template={detail} />
              )}
            </aside>
          </div>
        )}

        {step > 1 && !ready && (
          <div className="flex flex-col gap-3" aria-busy="true">
            <Skeleton className="h-9" />
            <div className="grid gap-3 md:grid-cols-2">
              <Skeleton className="h-40" />
              <Skeleton className="h-40" />
            </div>
          </div>
        )}

        {step === 2 && cfg && detail && (
          <div className="flex flex-col gap-4">
            <div className="grid gap-4 md:grid-cols-3">
              <FormField id="tw-name" label="Name" error={err('name')} className="md:col-span-3">
                <Input id="tw-name" value={cfg.name} onChange={(e) => (set('name', e.target.value), serverError?.field === 'name' && setServerError(null))} placeholder="e.g. Hardship Reply Drafter" autoFocus aria-invalid={!!err('name')} />
              </FormField>
              <FormField id="tw-owner" label="Owning team" error={err('owner')}>
                <Select value={cfg.owner} onValueChange={(v) => set('owner', v)}>
                  <SelectTrigger id="tw-owner" className="w-full" aria-invalid={!!err('owner')}>
                    <SelectValue placeholder="Choose a team" />
                  </SelectTrigger>
                  <SelectContent>
                    {lookups?.owners.map((o) => (
                      <SelectItem key={o} value={o}>
                        {o}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <FormField id="tw-model" label="Model" error={err('model')} hint={modelHint(models, cfg.model, `The template is tested on ${detail.model}.`)} className="md:col-span-2">
                <ModelSelect id="tw-model" value={cfg.model} onValueChange={(v) => set('model', v)} aliases={models} invalid={!!err('model')} />
              </FormField>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <FormField id="tw-kb" label="Knowledge bases" optional hint="Agents cite only what is attached.">
                <div className="flex flex-col gap-1.5" data-testid="tw-kb-list">
                  {missingKb.length > 0 && (
                    <p className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2.5 text-xs text-warning-text" role="status">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                      The template expects {missingKb.join(', ')}, which {missingKb.length === 1 ? 'does' : 'do'} not exist here. Its instructions mention {missingKb.length === 1 ? 'it' : 'them'}; create {missingKb.length === 1 ? 'it' : 'them'} in Knowledge bases or edit the instructions.
                    </p>
                  )}
                  {(lookups?.collections ?? []).map((k) => (
                    <label key={k} className="flex items-center gap-2 text-sm">
                      <Checkbox checked={cfg.collections.includes(k)} onCheckedChange={(c) => set('collections', c ? [...cfg.collections, k] : cfg.collections.filter((x) => x !== k))} />
                      {k}
                      {detail.expectedKnowledge.includes(k) && <span className="text-xs text-muted-foreground">expected</span>}
                    </label>
                  ))}
                </div>
              </FormField>
              <FormField id="tw-tools" label="Tool operations" optional hint="Only operations your team may grant are listed.">
                <div className="flex flex-col gap-1.5" data-testid="tw-tool-list">
                  {unavailable.length > 0 && (
                    <p className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 p-2.5 text-xs text-warning-text" role="status">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                      {unavailable.join(', ')} {unavailable.length === 1 ? 'is' : 'are'} not available to your team. Request access from the tool owner in Tools &amp; MCP, then grant it on the agent page.
                    </p>
                  )}
                  <div className="max-h-56 divide-y overflow-y-auto rounded-md border">
                    {[tools.filter((t) => !t.workflow), tools.filter((t) => t.workflow)].map((group, gi) =>
                      group.length ? (
                        <div key={gi} className="divide-y">
                          {gi === 1 && <p className="bg-muted/40 px-2.5 py-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Workflows</p>}
                          {group.map((t) => (
                            <label key={t.id} className={cn('flex cursor-pointer flex-wrap items-center gap-2 px-2.5 py-1.5 text-sm hover:bg-accent/40', cfg.toolIds.includes(t.id) && 'bg-primary/5')}>
                              <Checkbox checked={cfg.toolIds.includes(t.id)} onCheckedChange={(c) => set('toolIds', c ? [...cfg.toolIds, t.id] : cfg.toolIds.filter((x) => x !== t.id))} aria-label={t.name} />
                              <code className="font-mono text-xs">{t.name}</code>
                              <AccessBadge access={t.access} />
                              {t.requiresReview && <UserCheck className="size-3.5 text-warning-text" aria-label="Pauses for review" />}
                              {detail.expectedTools.some((x) => x.name === t.name) && <span className="ml-auto text-xs text-muted-foreground">expected</span>}
                              {t.workflow && (
                                <span className="basis-full pl-6">
                                  <WorkflowToolFacts workflow={t.workflow} />
                                </span>
                              )}
                            </label>
                          ))}
                        </div>
                      ) : null,
                    )}
                  </div>
                </div>
              </FormField>
            </div>
          </div>
        )}

        {step === 3 && cfg && detail && (
          <TemplateSkillsStep
            candidates={candidates}
            loading={skillCandidates.loading}
            error={skillCandidates.error}
            onRetry={skillCandidates.onRetry}
            suggestions={detail.suggestedSkills}
            value={cfg.skills}
            onChange={(v) => set('skills', v)}
            onBackToConfigure={() => setStep(2)}
            showErrors={touched}
          />
        )}

        {step === 4 && cfg && (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <Label htmlFor="tw-instructions">Instructions</Label>
              <div className="ml-auto flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setGenOpen(true)} data-testid="wizard-generate">
                  <Sparkles className="size-3.5" /> Generate with the prompt builder
                </Button>
              </div>
            </div>
            <Textarea
              id="tw-instructions"
              value={cfg.instructions}
              onChange={(e) => set('instructions', e.target.value)}
              className="min-h-72 font-mono text-[13px] leading-relaxed"
              placeholder="e.g. You draft replies to hardship emails. Always offer the hardship line first."
              aria-invalid={!!err('instructions')}
            />
            {err('instructions') ? <p className="text-xs text-destructive">{err('instructions')}</p> : <p className="text-xs text-muted-foreground">Prefilled from the template. Shared wording such as disclosures comes from the always-on skills chosen in Skills.</p>}
          </div>
        )}

        {step === 5 && cfg && (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-muted-foreground">The template’s defaults. They apply in every workflow that uses the agent.</p>
            <div className="grid gap-4 md:grid-cols-2">
              <FormField id="tw-unsure" label="When unsure">
                <Select value={cfg.guardrails.whenUnsure} onValueChange={(v) => set('guardrails', { ...cfg.guardrails, whenUnsure: v as AgentGuardrails['whenUnsure'] })}>
                  <SelectTrigger id="tw-unsure" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.entries(UNSURE).map(([v, l]) => (
                      <SelectItem key={v} value={v}>
                        {l}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <FormField id="tw-max" label="Tool calls per turn">
                <Select value={String(cfg.guardrails.maxToolCallsPerTurn)} onValueChange={(v) => set('guardrails', { ...cfg.guardrails, maxToolCallsPerTurn: Number(v) })}>
                  <SelectTrigger id="tw-max" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[2, 3, 4, 6, 8, 10].map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        At most {n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
            </div>
            <div className="flex items-start justify-between gap-4 rounded-lg border p-3">
              <div>
                <label htmlFor="tw-pii" className="text-sm font-medium">
                  Redact personal data
                </label>
                <p className="text-xs text-muted-foreground">Account numbers, SINs and card numbers are masked in logs and transcripts. Turning it off is a re-approval change.</p>
              </div>
              <Switch id="tw-pii" checked={cfg.guardrails.redactPii} onCheckedChange={(v) => set('guardrails', { ...cfg.guardrails, redactPii: v })} />
            </div>
            <FormField id="tw-topics" label="Blocked topics" optional hint="Press Enter or comma to add.">
              <TagInput id="tw-topics" value={cfg.guardrails.blockedTopics} onChange={(v) => set('guardrails', { ...cfg.guardrails, blockedTopics: v })} placeholder="e.g. Tax advice" />
            </FormField>
          </div>
        )}

        {step === 6 && cfg && detail && (
          <div className="flex flex-col gap-3">
            {serverError?.step === 6 && <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{serverError.message}</p>}
            {(
              [
                ['Template', 1, [['Template', `${detail.name} v${detail.version}`], ['Risk tier', detail.riskTier]]],
                ['Configure', 2, [['Name', cfg.name], ['Owning team', cfg.owner], ['Model', cfg.model], ['Knowledge', cfg.collections.join(', ') || 'None'], ['Tools', granted.map((t) => t.name).join(', ') || 'None']]],
                ['Skills', 3, [['Skills', cfg.skills.map((p) => `${candidates?.attachable.find((c) => c.skillId === p.skillId)?.name ?? p.skillId} v${p.version}`).join(', ') || 'None']]],
                ['Instructions', 4, [['Length', `${cfg.instructions.length.toLocaleString()} characters`]]],
                ['Guardrails', 5, [['When unsure', UNSURE[cfg.guardrails.whenUnsure]], ['Tool calls per turn', `At most ${cfg.guardrails.maxToolCallsPerTurn}`], ['Redact personal data', cfg.guardrails.redactPii ? 'On' : 'Off'], ['Blocked topics', cfg.guardrails.blockedTopics.join(', ') || 'None']]],
              ] as [string, number, [string, React.ReactNode][]][]
            ).map(([title, target, rows]) => (
              <div key={title} className="rounded-lg border">
                <div className="flex items-center justify-between border-b px-3 py-1.5">
                  <span className="text-sm font-medium">{title}</span>
                  <Button variant="ghost" size="sm" className="h-7" onClick={() => setStep(target)}>
                    <Pencil className="size-3.5" /> Edit
                  </Button>
                </div>
                <div className="px-3">
                  <KeyValues rows={rows} />
                </div>
              </div>
            ))}
            {detail.starterTests.length > 0 && (
              <div className="rounded-lg border p-3">
                <label className="flex items-center gap-2 text-sm font-medium">
                  <Checkbox checked={cfg.includeTests} onCheckedChange={(c) => set('includeTests', !!c)} aria-label="Add the starter tests" />
                  <FlaskConical className="size-4 text-muted-foreground" /> Add {plural(detail.starterTests.length, 'starter test')} to the agent’s evals
                </label>
                <ul className="mt-2 flex flex-col gap-1 pl-6 text-xs text-muted-foreground">
                  {detail.starterTests.map((t) => (
                    <li key={t.name}>{t.name}</li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-xs text-muted-foreground">The agent starts as a draft at v1. Add it to a workflow to put it to work; nothing reaches production until a workflow that uses it is published.</p>
          </div>
        )}
      </DialogShell>

      {cfg && (
        <>
          <PromptGeneratorDialog
            open={genOpen}
            onOpenChange={setGenOpen}
            backend={generator}
            context={{ model: cfg.model, grantedTools: granted.map((t) => t.name), collections: cfg.collections }}
            initial={initialSpec({ role: detail?.role || cfg.name, channels: detail?.channels ?? ['chat'], tools: granted.map((t) => t.name), collections: cfg.collections, guardrails: cfg.guardrails, toolHints: Object.fromEntries((detail?.expectedTools ?? []).map((x) => [x.name, `you need to ${x.purpose.replace(/^./, (c) => c.toLowerCase())}`])) })}
            currentInstructions={cfg.instructions}
            onApply={(text) => set('instructions', text)}
            applyNote="Applying replaces the instructions in this wizard. Nothing is saved until you create the agent."
          />
        </>
      )}
    </>
  );
}
