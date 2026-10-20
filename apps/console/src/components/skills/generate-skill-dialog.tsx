'use client';

import * as React from 'react';
import { AlertTriangle, BookOpen, Bot, CheckCircle2, FileText, History, LayoutTemplate, ListChecks, Loader2, Pencil, Play, Plus, RefreshCw, Search, Sparkles, Square, Wand2, X, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import { CheckChips } from '@/components/evals/eval-meta';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FileUpload, type UploadItem, uploadsBlocker, uploadsReady } from '@/components/shared/file-upload';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Stepper } from '@/components/shared/stepper';
import { TagInput } from '@/components/shared/tag-input';
import { AccessBadge } from '@/components/status-badges';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import type { SkillGeneratorBackend } from '@/hooks/skill-queries';
import { plural } from '@/lib/format';
import type { Skill, SkillDraftForCheck, SkillGenerateInput, SkillImpact, SkillLoading, SkillSectionKey, SkillStart, SkillStartKind, SkillTestCaseInput, SkillTestRun } from '@/lib/types/skills';
import { cn } from '@/lib/utils';

import { SKILL_LOADING_LABEL, SkillLoadingField } from './skill-loading';
import { joinSections, SECTION_TITLE, SECTIONS } from './skill-meta';
import { SkillTestDialog } from './skill-test-dialog';

const STEPS = ['Start from', 'Scope', 'Draft', 'Tests', 'Review'] as const;

const STARTS: { kind: SkillStartKind; label: string; hint: string; icon: typeof Sparkles }[] = [
  { kind: 'describe', label: 'Describe the task', hint: 'Say in your words what the agent should do and when.', icon: Pencil },
  { kind: 'document', label: 'An existing document', hint: 'A procedure in a knowledge base, or an SOP you upload.', icon: FileText },
  { kind: 'past_work', label: 'Past work', hint: 'Resolved cases or chats the skill should repeat.', icon: History },
  { kind: 'template', label: 'A template', hint: 'Email reply, extraction, policy Q&A, triage or a memo.', icon: LayoutTemplate },
];

interface Draft {
  name: string;
  useWhen: string;
  loading: SkillLoading;
  sections: Record<SkillSectionKey, string>;
  toolIds: string[];
  knowledgeBases: string[];
  guardrails: string[];
}

const EMPTY_DRAFT: Draft = { name: '', useWhen: '', loading: 'on_match', sections: { steps: '', rules: '', examples: '', output_format: '' }, toolIds: [], knowledgeBases: [], guardrails: [] };

function Pick({ checked, onChange, children, testId, disabled }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode; testId?: string; disabled?: boolean }) {
  return (
    <label className={cn('flex cursor-pointer items-start gap-3 px-3 py-2 hover:bg-muted/40', checked && 'bg-primary/5', disabled && 'cursor-not-allowed opacity-60')} data-testid={testId}>
      <Checkbox checked={checked} onCheckedChange={(v) => onChange(!!v)} className="mt-0.5" disabled={disabled} />
      <div className="min-w-0 flex-1 text-sm">{children}</div>
    </label>
  );
}

/**
 * Generate skill, in five steps. Every model call (draft, rewrite, suggested tests) goes through the AI gateway and
 * nothing is stored until Save; the result is always a draft that needs a reviewer before agents can use it.
 */
export function GenerateSkillDialog({
  open,
  onOpenChange,
  backend,
  defaultTeam,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  backend: SkillGeneratorBackend;
  defaultTeam?: string;
  onSaved: (skill: Skill, requested: boolean) => void;
}) {
  const { options, generation, rewrite, suggestTests, dryRun, impact, create } = backend;
  const opts = options.data;
  const [step, setStep] = React.useState(1);
  const [kind, setKind] = React.useState<SkillStartKind>('describe');
  const [describe, setDescribe] = React.useState('');
  const [docIds, setDocIds] = React.useState<string[]>([]);
  const [uploads, setUploads] = React.useState<UploadItem[]>([]);
  const [pastIds, setPastIds] = React.useState<string[]>([]);
  const [pastQuery, setPastQuery] = React.useState('');
  const [templateId, setTemplateId] = React.useState('');
  const [templateText, setTemplateText] = React.useState('');
  const [targets, setTargets] = React.useState<string[]>([]);
  const [team, setTeam] = React.useState('');
  const [toolIds, setToolIds] = React.useState<string[]>([]);
  const [kbs, setKbs] = React.useState<string[]>([]);
  const [riskNotes, setRiskNotes] = React.useState('');
  const [draft, setDraft] = React.useState<Draft>(EMPTY_DRAFT);
  const [generatedFor, setGeneratedFor] = React.useState('');
  const [rewriting, setRewriting] = React.useState<{ section: SkillSectionKey; instruction: string } | null>(null);
  const [tests, setTests] = React.useState<SkillTestCaseInput[] | null>(null);
  const [testDialog, setTestDialog] = React.useState<{ index: number | null } | null>(null);
  const [run, setRun] = React.useState<SkillTestRun | null>(null);
  const [impacts, setImpacts] = React.useState<SkillImpact[] | null>(null);
  const [reviewNote, setReviewNote] = React.useState('');
  const [showErrors, setShowErrors] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const bodyRef = React.useRef<HTMLDivElement>(null);
  const gen = generation.state;

  React.useEffect(() => {
    if (!open) return;
    setStep(1);
    setKind('describe');
    setDescribe('');
    setDocIds([]);
    setUploads([]);
    setPastIds([]);
    setPastQuery('');
    setTemplateId('');
    setTemplateText('');
    setTargets([]);
    setTeam('');
    setToolIds([]);
    setKbs([]);
    setRiskNotes('');
    setDraft(EMPTY_DRAFT);
    setGeneratedFor('');
    setTests(null);
    setRun(null);
    setImpacts(null);
    setReviewNote('');
    setShowErrors(false);
    setSaveError(null);
    generation.reset();
    // Only on open: the backend object is new on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  React.useEffect(() => {
    if (open && !team && opts?.teams.length) setTeam(defaultTeam && opts.teams.includes(defaultTeam) ? defaultTeam : opts.teams[0]);
  }, [open, team, opts, defaultTeam]);
  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);

  // The generated draft becomes editable once streaming finishes.
  React.useEffect(() => {
    if (gen.phase !== 'done' || !gen.skill) return;
    const sk = gen.skill;
    setDraft((d) => ({ name: sk.name, useWhen: sk.useWhen, loading: d.loading, sections: sk.sections, toolIds: sk.tools.map((t) => t.toolId), knowledgeBases: sk.knowledgeBases, guardrails: sk.guardrails }));
  }, [gen.phase, gen.skill]);

  const fileIds = uploadsReady(uploads) ? uploads.map((u) => u.fileId!) : [];
  const start: SkillStart =
    kind === 'describe' ? { kind, text: describe.trim() } : kind === 'document' ? { kind, documentIds: docIds, fileIds } : kind === 'past_work' ? { kind, itemIds: pastIds } : { kind, templateId, text: templateText.trim() || undefined };
  const input: SkillGenerateInput = { start, scope: { targetAgentIds: targets, ownerTeam: team, toolIds, knowledgeBases: kbs, riskNotes } };
  const inputKey = JSON.stringify(input);

  const startError =
    kind === 'describe'
      ? describe.trim().length < 20
        ? 'Describe the task in a sentence or two (at least 20 characters).'
        : undefined
      : kind === 'document'
        ? uploads.length && uploadsBlocker(uploads)
          ? uploadsBlocker(uploads)
          : !docIds.length && !fileIds.length
            ? 'Choose a document or upload one.'
            : undefined
        : kind === 'past_work'
          ? !pastIds.length
            ? 'Choose at least one case or chat.'
            : undefined
          : !templateId
            ? 'Choose a template.'
            : undefined;
  const scopeError = !team ? 'Choose the owner team.' : undefined;
  const toolName = (tid: string) => opts?.tools.find((t) => t.toolId === tid)?.name ?? tid;
  const outTools = draft.toolIds.filter((t) => !toolIds.includes(t));
  const outKbs = draft.knowledgeBases.filter((k) => !kbs.includes(k));
  const agentWarnings = (gen.skill?.warnings ?? []).filter((w) => w.kind === 'agent_lacks' && targets.includes(w.ref.split(':')[0]));
  const draftErrors = {
    generating: gen.phase === 'streaming' ? 'Wait for the draft to finish.' : gen.phase === 'stopped' ? 'Generation stopped before it finished. Regenerate to continue.' : gen.phase === 'error' ? (gen.error ?? 'Generation failed.') : gen.phase !== 'done' ? 'Generate the draft.' : undefined,
    name: !draft.name.trim() ? 'Name the skill.' : undefined,
    useWhen: !draft.useWhen.trim() && draft.loading === 'on_match' ? 'Say when the skill should be used.' : draft.useWhen.length > (opts?.limits.useWhenMaxChars ?? 1024) ? `Keep it under ${opts?.limits.useWhenMaxChars ?? 1024} characters.` : undefined,
    sections: SECTIONS.some((k) => !draft.sections[k].trim()) ? 'Every section needs text.' : undefined,
    scope: outTools.length || outKbs.length ? 'Resolve the warnings: remove each item outside the scope, or add it to the scope.' : undefined,
  };
  const draftError = Object.values(draftErrors).find(Boolean);
  const testsError = tests && !tests.length ? 'Add at least one test case.' : undefined;
  const stepError = step === 1 ? startError : step === 2 ? scopeError : step === 3 ? draftError : step === 4 ? testsError : undefined;

  const checkDraft: SkillDraftForCheck = { name: draft.name, useWhen: draft.useWhen, loading: draft.loading, instructions: joinSections(draft.sections), toolIds: draft.toolIds, knowledgeBases: draft.knowledgeBases, guardrails: draft.guardrails };

  const go = (n: number) => {
    setShowErrors(false);
    setStep(n);
    if (n === 3 && generatedFor !== inputKey) {
      setGeneratedFor(inputKey);
      setDraft(EMPTY_DRAFT);
      setTests(null);
      void generation.start(input);
    }
    if (n === 4 && tests === null && gen.skill) {
      suggestTests.mutate({ input, skill: { ...gen.skill, name: draft.name, useWhen: draft.useWhen, tools: (opts?.tools ?? []).filter((t) => draft.toolIds.includes(t.toolId)), knowledgeBases: draft.knowledgeBases } }, { onSuccess: setTests, onError: () => setTests([]) });
    }
    if (n === 5) {
      setRun(null);
      setImpacts(null);
      if (targets.length) impact.mutate({ draft: checkDraft, agentIds: targets }, { onSuccess: setImpacts });
    }
  };
  const next = () => {
    if (stepError) return setShowErrors(true);
    go(step + 1);
  };

  const regenerate = () => {
    setDraft(EMPTY_DRAFT);
    setTests(null);
    setGeneratedFor(inputKey);
    void generation.start(input);
  };

  const applyRewrite = () => {
    if (!rewriting?.instruction.trim()) return;
    const before = draft.sections[rewriting.section];
    const section = rewriting.section;
    rewrite.mutate(
      { section, current: before, instruction: rewriting.instruction, name: draft.name, scope: input.scope },
      {
        onSuccess: ({ text }) => {
          setDraft((d) => ({ ...d, sections: { ...d.sections, [section]: text } }));
          setRewriting(null);
          toast.success(`Rewrote ${SECTION_TITLE[section]}`, { action: { label: 'Undo', onClick: () => setDraft((d) => ({ ...d, sections: { ...d.sections, [section]: before } })) } });
        },
        onError: (e) => toast.error('Couldn’t rewrite the section', { description: e.message }),
      },
    );
  };

  const provenance = () => {
    if (!opts) return '';
    if (kind === 'describe') return 'Generated from a description';
    if (kind === 'document') return `Generated from ${[...opts.documents.filter((d) => docIds.includes(d.id)).map((d) => d.title), ...(fileIds.length ? [plural(fileIds.length, 'uploaded SOP')] : [])].join(', ')}`;
    if (kind === 'past_work') return `Generated from ${plural(pastIds.length, 'past item')}`;
    return `Generated from the ${opts.templates.find((t) => t.id === templateId)?.name ?? ''} template`;
  };

  const save = async (requestReview: boolean) => {
    setSaveError(null);
    try {
      const s = await create.mutateAsync({
        name: draft.name.trim(),
        useWhen: draft.loading === 'always' ? '' : draft.useWhen.trim(),
        loading: draft.loading,
        instructions: joinSections(draft.sections),
        ownerTeam: team,
        toolIds: draft.toolIds,
        knowledgeBases: draft.knowledgeBases,
        guardrails: draft.guardrails,
        tests: tests ?? [],
        origin: 'generated',
        provenance: { detail: provenance(), citations: gen.skill?.citations ?? [] },
        gatewayCallId: gen.skill?.gatewayCallId,
        targetAgentIds: targets,
        requestReview,
        reviewNote: reviewNote.trim() || undefined,
      });
      onSaved(s, requestReview);
      onOpenChange(false);
    } catch (e) {
      setSaveError((e as Error).message);
    }
  };

  const pastGroups = React.useMemo(() => {
    const q = pastQuery.trim().toLowerCase();
    const items = (opts?.pastWork ?? []).filter((p) => !q || `${p.title} ${p.detail} ${p.group} ${p.id}`.toLowerCase().includes(q));
    const groups = new Map<string, typeof items>();
    for (const p of items) groups.set(p.group, [...(groups.get(p.group) ?? []), p]);
    return [...groups.entries()];
  }, [opts?.pastWork, pastQuery]);

  const toolsByModule = React.useMemo(() => {
    const m = new Map<string, NonNullable<typeof opts>['tools']>();
    for (const t of opts?.tools ?? []) m.set(t.module, [...(m.get(t.module) ?? []), t]);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [opts?.tools]);

  const toggle = (list: string[], set: (v: string[]) => void, v: string, on: boolean) => set(on ? [...new Set([...list, v])] : list.filter((x) => x !== v));
  const err = (m?: string) => (showErrors && m ? <p className="text-sm text-destructive" role="alert">{m}</p> : null);

  const body = () => {
    if (options.isPending) return <Skeleton className="h-64 w-full" />;
    if (options.isError || !opts) return <QueryError what="what a skill can start from" onRetry={() => options.refetch()} retrying={options.isFetching} />;

    if (step === 1)
      return (
        <div className="flex flex-col gap-4" data-testid="gen-step-start">
          <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Start from">
            {STARTS.map((s) => (
              <button
                key={s.kind}
                type="button"
                role="radio"
                aria-checked={kind === s.kind}
                onClick={() => (setKind(s.kind), setShowErrors(false))}
                className={cn('flex items-start gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', kind === s.kind && 'border-primary bg-primary/5')}
                data-testid={`gen-start-${s.kind}`}
              >
                <s.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span>
                  <span className="block text-sm font-medium">{s.label}</span>
                  <span className="block text-xs text-muted-foreground">{s.hint}</span>
                </span>
              </button>
            ))}
          </div>
          {kind === 'describe' && (
            <FormField id="gen-describe" label="What should the agent do, and when?" error={showErrors ? startError : undefined} hint="Name the request, the systems involved and what a good outcome looks like.">
              <Textarea id="gen-describe" aria-invalid={showErrors && !!startError} value={describe} onChange={(e) => setDescribe(e.target.value)} className="min-h-32" placeholder="e.g. When a borrower writes in about losing their job, check the loan, find the hardship option that fits and open a case for a specialist." />
            </FormField>
          )}
          {kind === 'document' && (
            <div className="flex flex-col gap-3">
              <span className="text-sm font-medium">Knowledge documents</span>
              <div className="divide-y rounded-md border" data-testid="gen-documents">
                {opts.documents.map((d) => (
                  <Pick key={d.id} checked={docIds.includes(d.id)} onChange={(v) => toggle(docIds, setDocIds, d.id, v)}>
                    <div className="flex items-center gap-2 font-medium">
                      <BookOpen className="size-3.5 text-muted-foreground" /> {d.title}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {d.kb} · {d.detail}
                    </div>
                  </Pick>
                ))}
              </div>
              <FileUpload id="gen-sop" purpose="skill_resource" multiple title="Or upload an SOP" hint="Stored through Files and scanned before the model reads it." onChange={setUploads} testId="gen-sop-upload" />
              {err(startError)}
            </div>
          )}
          {kind === 'past_work' && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <div className="relative flex-1">
                  <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
                  <Input value={pastQuery} onChange={(e) => setPastQuery(e.target.value)} placeholder="Search cases and chats…" className="pl-8" aria-label="Search past work" />
                </div>
                <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">{plural(pastIds.length, 'item')} chosen</span>
              </div>
              {pastGroups.length ? (
                <div className="flex flex-col gap-3" data-testid="gen-past-work">
                  {pastGroups.map(([group, items]) => {
                    const all = items.every((i) => pastIds.includes(i.id));
                    return (
                      <div key={group} className="overflow-hidden rounded-md border">
                        <div className="flex items-center justify-between bg-muted/40 px-3 py-1.5">
                          <span className="text-xs font-medium">
                            {group} · {items.length}
                          </span>
                          <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => setPastIds(all ? pastIds.filter((x) => !items.some((i) => i.id === x)) : [...new Set([...pastIds, ...items.map((i) => i.id)])])}>
                            {all ? 'Clear' : `Select all ${items.length}`}
                          </Button>
                        </div>
                        <div className="max-h-48 divide-y overflow-y-auto">
                          {items.map((p) => (
                            <Pick key={p.id} checked={pastIds.includes(p.id)} onChange={(v) => toggle(pastIds, setPastIds, p.id, v)}>
                              <div className="truncate font-medium">{p.title}</div>
                              <div className="truncate text-xs text-muted-foreground">
                                {p.kind === 'chat' ? 'Chat' : 'Case'} {p.id} · {p.detail}
                              </div>
                            </Pick>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">{pastQuery ? 'Nothing matches. Clear the search to see every case and chat.' : 'No cases or chats in this team yet.'}</p>
              )}
              {err(startError)}
            </div>
          )}
          {kind === 'template' && (
            <div className="flex flex-col gap-3">
              <div className="grid gap-2 sm:grid-cols-2" data-testid="gen-templates">
                {opts.templates.map((t) => (
                  <button key={t.id} type="button" aria-pressed={templateId === t.id} onClick={() => setTemplateId(t.id)} className={cn('rounded-lg border p-3 text-left hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', templateId === t.id && 'border-primary bg-primary/5')}>
                    <span className="block text-sm font-medium">{t.name}</span>
                    <span className="block text-xs text-muted-foreground">{t.description}</span>
                  </button>
                ))}
              </div>
              <FormField id="gen-template-text" label="What is it for?" optional hint="Narrows the template to your task.">
                <Input id="gen-template-text" value={templateText} onChange={(e) => setTemplateText(e.target.value)} placeholder="e.g. Payoff statement requests from lawyers" />
              </FormField>
              {err(startError)}
            </div>
          )}
        </div>
      );

    if (step === 2)
      return (
        <div className="grid gap-5 lg:grid-cols-2" data-testid="gen-step-scope">
          <div className="flex flex-col gap-4">
            <FormField id="gen-team" label="Owner team" error={showErrors ? scopeError : undefined} hint="Owns the skill, its reviews and its versions.">
              <Select value={team} onValueChange={setTeam}>
                <SelectTrigger id="gen-team" className="w-full" aria-invalid={showErrors && !!scopeError}>
                  <SelectValue placeholder="Choose a team" />
                </SelectTrigger>
                <SelectContent>
                  {opts.teams.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">
                Target agents <span className="font-normal text-muted-foreground">(optional)</span>
              </span>
              <p className="text-xs text-muted-foreground">You attach it after it is published. The review step shows what it adds to each.</p>
              <div className="max-h-40 divide-y overflow-y-auto rounded-md border" data-testid="gen-agents">
                {opts.agents.map((a) => (
                  <Pick key={a.id} checked={targets.includes(a.id)} onChange={(v) => toggle(targets, setTargets, a.id, v)}>
                    <div className="flex items-center gap-2">
                      <Bot className="size-3.5 text-muted-foreground" /> <span className="font-medium">{a.name}</span>
                      <span className="text-xs text-muted-foreground">{a.owner}</span>
                    </div>
                  </Pick>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">
                Knowledge bases <span className="font-normal text-muted-foreground">(optional)</span>
              </span>
              <div className="flex flex-wrap gap-1.5" data-testid="gen-kbs">
                {opts.knowledgeBases.map((k) => {
                  const on = kbs.includes(k);
                  return (
                    <button key={k} type="button" aria-pressed={on} onClick={() => toggle(kbs, setKbs, k, !on)} className="rounded-md focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                      <Badge variant={on ? 'default' : 'outline'} className="cursor-pointer font-normal">
                        {k}
                      </Badge>
                    </button>
                  );
                })}
              </div>
            </div>
            <FormField id="gen-risk" label="Risk notes" optional hint="What the skill must never do. Becomes guardrails and test cases.">
              <Textarea id="gen-risk" value={riskNotes} onChange={(e) => setRiskNotes(e.target.value)} className="min-h-20" placeholder="e.g. Never promise a deferral; a specialist decides." />
            </FormField>
          </div>
          <div className="flex min-w-0 flex-col gap-1.5">
            <span className="text-sm font-medium">
              Systems it may touch <span className="font-normal text-muted-foreground">({plural(toolIds.length, 'operation')} chosen)</span>
            </span>
            <p className="text-xs text-muted-foreground">Tool operations its steps may call. A skill never grants them: an agent must already hold each one.</p>
            <div className="max-h-[46vh] overflow-y-auto rounded-md border" data-testid="gen-tools">
              {toolsByModule.map(([mod, tools]) => (
                <div key={mod}>
                  <div className="sticky top-0 z-10 border-b bg-muted/60 px-3 py-1.5 text-xs font-medium backdrop-blur">{mod}</div>
                  <div className="divide-y">
                    {tools.map((t) => (
                      <Pick key={t.toolId} checked={toolIds.includes(t.toolId)} onChange={(v) => toggle(toolIds, setToolIds, t.toolId, v)}>
                        <div className="flex items-center justify-between gap-2">
                          <code className="truncate font-mono text-xs">{t.name}</code>
                          <AccessBadge access={t.access} />
                        </div>
                      </Pick>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      );

    if (step === 3)
      return (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]" data-testid="gen-step-draft">
          <div className="flex min-w-0 flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 px-3 py-2 text-sm" aria-live="polite">
              {gen.phase === 'streaming' ? <Loader2 className="size-4 animate-spin text-primary" /> : gen.phase === 'done' ? <CheckCircle2 className="size-4 text-success-text" /> : gen.phase === 'error' ? <XCircle className="size-4 text-destructive" /> : <Sparkles className="size-4 text-muted-foreground" />}
              <span className="min-w-0 flex-1 truncate" data-testid="gen-status">
                {gen.phase === 'streaming' ? gen.status : gen.phase === 'done' ? `Drafted through the AI gateway · ${gen.skill?.model}` : gen.phase === 'stopped' ? 'Stopped. Regenerate to finish the draft.' : gen.phase === 'error' ? gen.error : 'Ready to draft'}
              </span>
              {gen.phase === 'streaming' ? (
                <Button variant="outline" size="sm" className="h-7" onClick={generation.stop} data-testid="gen-stop">
                  <Square className="size-3" /> Stop
                </Button>
              ) : (
                <Button variant="outline" size="sm" className="h-7" onClick={regenerate} data-testid="gen-regenerate">
                  <RefreshCw className="size-3.5" /> Regenerate
                </Button>
              )}
            </div>
            <FormField id="gen-name" label="Name" error={showErrors && gen.phase === 'done' ? draftErrors.name : undefined}>
              <Input id="gen-name" value={gen.phase === 'done' ? draft.name : gen.name} readOnly={gen.phase !== 'done'} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. Hardship request triage" />
            </FormField>
            <SkillLoadingField id="gen-loading" value={draft.loading} onChange={(loading) => setDraft((d) => ({ ...d, loading }))} />
            {draft.loading === 'on_match' && (
            <FormField id="gen-usewhen" label="Use when" error={showErrors && gen.phase === 'done' ? draftErrors.useWhen : undefined} hint={`What the model reads to decide to load the skill. ${(gen.phase === 'done' ? draft.useWhen : gen.useWhen).length} of ${opts.limits.useWhenMaxChars} characters.`}>
              <Textarea id="gen-usewhen" value={gen.phase === 'done' ? draft.useWhen : gen.useWhen} readOnly={gen.phase !== 'done'} onChange={(e) => setDraft({ ...draft, useWhen: e.target.value })} className="min-h-16" />
            </FormField>
            )}
            {SECTIONS.map((k) => {
              const text = gen.phase === 'done' ? draft.sections[k] : gen.sections[k];
              const open = rewriting?.section === k;
              return (
                <div key={k} className="flex flex-col gap-1.5" data-testid={`gen-section-${k}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{SECTION_TITLE[k]}</span>
                    <Button variant="ghost" size="sm" className="h-7 text-xs" disabled={gen.phase !== 'done'} onClick={() => setRewriting(open ? null : { section: k, instruction: '' })} data-testid={`gen-rewrite-${k}`}>
                      <Wand2 className="size-3.5" /> Rewrite with instruction
                    </Button>
                  </div>
                  {open && (
                    <div className="flex gap-2">
                      <Input autoFocus aria-label={`How to rewrite ${SECTION_TITLE[k]}`} value={rewriting.instruction} onChange={(e) => setRewriting({ section: k, instruction: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && applyRewrite()} placeholder="e.g. Make it shorter, or Add a rule about joint accounts" />
                      <LoadingButton size="sm" isLoading={rewrite.isPending} disabled={!rewriting.instruction.trim()} onClick={applyRewrite} data-testid="gen-rewrite-apply">
                        Rewrite
                      </LoadingButton>
                    </div>
                  )}
                  <Textarea value={text} readOnly={gen.phase !== 'done'} onChange={(e) => setDraft({ ...draft, sections: { ...draft.sections, [k]: e.target.value } })} className={cn('min-h-24 font-mono text-xs leading-relaxed', gen.phase === 'streaming' && 'bg-muted/30')} aria-label={SECTION_TITLE[k]} />
                </div>
              );
            })}
            {showErrors && draftError && <p className="text-sm text-destructive" role="alert">{draftError}</p>}
          </div>
          <aside className="flex min-w-0 flex-col gap-4">
            {gen.phase === 'done' && (outTools.length > 0 || outKbs.length > 0 || agentWarnings.length > 0) && (
              <div className="flex flex-col gap-2 rounded-md border border-warning/40 bg-warning/5 p-3" data-testid="gen-warnings">
                <span className="flex items-center gap-1.5 text-sm font-medium text-warning-text">
                  <AlertTriangle className="size-4" /> {plural(outTools.length + outKbs.length + agentWarnings.length, 'warning')}
                </span>
                {outTools.map((t) => (
                  <div key={t} className="flex flex-col gap-1 text-xs">
                    <span>
                      Calls <code className="font-mono">{toolName(t)}</code>, which is not in scope.
                    </span>
                    <span className="flex gap-1">
                      <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => setToolIds([...toolIds, t])}>
                        Add to scope
                      </Button>
                      <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => setDraft({ ...draft, toolIds: draft.toolIds.filter((x) => x !== t) })}>
                        Remove from skill
                      </Button>
                    </span>
                  </div>
                ))}
                {outKbs.map((k) => (
                  <div key={k} className="flex flex-col gap-1 text-xs">
                    <span>Cites {k}, which is not in scope.</span>
                    <span className="flex gap-1">
                      <Button variant="outline" size="sm" className="h-6 px-2 text-xs" onClick={() => setKbs([...kbs, k])}>
                        Add to scope
                      </Button>
                      <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => setDraft({ ...draft, knowledgeBases: draft.knowledgeBases.filter((x) => x !== k) })}>
                        Remove from skill
                      </Button>
                    </span>
                  </div>
                ))}
                {agentWarnings.map((w) => (
                  <p key={w.ref} className="text-xs text-muted-foreground">
                    {w.message}
                  </p>
                ))}
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Tools</span>
              {gen.phase === 'done' ? (
                draft.toolIds.length ? (
                  <div className="flex flex-wrap gap-1">
                    {draft.toolIds.map((t) => (
                      <Badge key={t} variant="secondary" className={cn('gap-1 font-mono text-[11px] font-normal', outTools.includes(t) && 'border-warning/40 bg-warning/10')}>
                        {toolName(t)}
                        <button type="button" aria-label={`Remove ${toolName(t)}`} onClick={() => setDraft({ ...draft, toolIds: draft.toolIds.filter((x) => x !== t) })}>
                          <X className="size-3" />
                        </button>
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground">None</span>
                )
              ) : (
                <Skeleton className="h-6 w-40" />
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Knowledge bases</span>
              {gen.phase === 'done' ? <span className="text-sm">{draft.knowledgeBases.join(', ') || 'None'}</span> : <Skeleton className="h-5 w-32" />}
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">Guardrails</span>
              {gen.phase === 'done' ? <TagInput value={draft.guardrails} onChange={(g) => setDraft({ ...draft, guardrails: g })} placeholder="Add a guardrail and press Enter" /> : <Skeleton className="h-9 w-full" />}
            </div>
            <div className="flex flex-col gap-1.5" data-testid="gen-citations">
              <span className="text-xs font-medium text-muted-foreground">Sources</span>
              {gen.phase === 'done' && gen.skill?.citations.length ? (
                <ul className="flex flex-col gap-1.5 text-xs">
                  {gen.skill.citations.map((c) => (
                    <li key={c.id} className="rounded-md border px-2 py-1.5">
                      <div className="flex items-center gap-1.5 font-medium">
                        <BookOpen className="size-3 text-muted-foreground" />
                        {c.href ? (
                          <a href={c.href} target="_blank" rel="noopener" className="truncate underline-offset-2 hover:underline">
                            {c.label}
                          </a>
                        ) : (
                          <span className="truncate">{c.label}</span>
                        )}
                      </div>
                      <div className="text-muted-foreground">
                        {c.section === 'use_when' ? 'Use when' : SECTION_TITLE[c.section]}
                        {c.detail ? ` · ${c.detail}` : ''}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : gen.phase === 'done' ? (
                <span className="text-xs text-muted-foreground">None</span>
              ) : (
                <Skeleton className="h-12 w-full" />
              )}
            </div>
          </aside>
        </div>
      );

    if (step === 4)
      return (
        <div className="flex flex-col gap-3" data-testid="gen-step-tests">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm text-muted-foreground">Drawn from the sources. Each runs before the skill can go to review. Edit them to match what a reviewer expects.</p>
            <Button variant="outline" size="sm" onClick={() => setTestDialog({ index: null })} disabled={tests === null}>
              <Plus className="size-3.5" /> Add case
            </Button>
          </div>
          {tests === null ? (
            [0, 1, 2].map((i) => <Skeleton key={i} className="h-20 w-full" />)
          ) : tests.length ? (
            <ul className="flex flex-col gap-2" data-testid="gen-tests">
              {tests.map((t, i) => (
                <li key={i} className="flex items-start gap-3 rounded-lg border p-3">
                  <ListChecks className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{t.name}</div>
                    <p className="truncate text-xs text-muted-foreground">{t.input}</p>
                    <div className="mt-1.5">
                      <CheckChips checks={t.checks} max={4} />
                    </div>
                  </div>
                  <Button variant="ghost" size="sm" className="h-7" onClick={() => setTestDialog({ index: i })}>
                    Edit
                  </Button>
                  <Button variant="ghost" size="icon" className="size-7" aria-label={`Remove ${t.name}`} onClick={() => setTests(tests.filter((_, j) => j !== i))}>
                    <X className="size-3.5" />
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">No test cases. Add one so the skill can be reviewed.</p>
          )}
          {err(testsError)}
        </div>
      );

    const startLabel = STARTS.find((s) => s.kind === kind)!.label;
    return (
      <div className="flex flex-col gap-5" data-testid="gen-step-review">
        <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border bg-border text-sm sm:grid-cols-2">
          {(
            [
              ['Start from', `${startLabel} · ${provenance()}`, 1],
              ['Owner team', team, 2],
              ['Name', draft.name, 3],
              ['Loading', SKILL_LOADING_LABEL[draft.loading], 3],
              ...(draft.loading === 'on_match' ? [['Use when', draft.useWhen, 3] as const] : []),
              ['Tools', draft.toolIds.map(toolName).join(', ') || 'None', 3],
              ['Knowledge bases', draft.knowledgeBases.join(', ') || 'None', 3],
              ['Guardrails', draft.guardrails.join(' · ') || 'None', 3],
              ['Tests', plural(tests?.length ?? 0, 'case'), 4],
            ] as [string, string, number][]
          ).map(([k, v, s]) => (
            <div key={k} className="flex items-start gap-2 bg-card p-3">
              <div className="min-w-0 flex-1">
                <dt className="text-xs text-muted-foreground">{k}</dt>
                <dd className="mt-0.5 break-words">{v}</dd>
              </div>
              <Button variant="ghost" size="sm" className="h-6 px-2 text-xs" onClick={() => go(s)} aria-label={`Edit ${k.toLowerCase()}`}>
                Edit
              </Button>
            </div>
          ))}
        </dl>

        <section className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">What it adds to each target agent</span>
            {!targets.length && (
              <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => go(2)}>
                Choose agents
              </Button>
            )}
          </div>
          {!targets.length ? (
            <p className="text-sm text-muted-foreground">No target agents. Attach the skill from an agent’s page once it is published.</p>
          ) : !impacts ? (
            <Skeleton className="h-24 w-full" />
          ) : (
            <div className="grid gap-2 md:grid-cols-2" data-testid="gen-impact">
              {impacts.map((m) => (
                <div key={m.agentId} className="flex flex-col gap-2 rounded-lg border p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-1.5 text-sm font-medium">
                      <Bot className="size-3.5 text-muted-foreground" /> {m.agentName}
                    </span>
                    {m.attachable ? <span className="text-success-text">Can attach</span> : <span className="text-destructive">Cannot attach yet</span>}
                  </div>
                  <div className="font-mono leading-relaxed">
                    {m.skillsBefore.map((s) => (
                      <div key={s} className="text-muted-foreground">
                        {'  '}
                        {s}
                      </div>
                    ))}
                    <div className="bg-success/10 text-success-text">+ {m.skillsAfter[m.skillsAfter.length - 1]}</div>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Tools held: </span>
                    {m.toolsHeld.join(', ') || 'none needed'}
                  </div>
                  {(m.toolsMissing.length > 0 || m.kbsMissing.length > 0) && <div className="text-destructive">Missing: {[...m.toolsMissing, ...m.kbsMissing].join(', ')}. Grant them on the agent first.</div>}
                  {m.guardrailsAdded.length > 0 && (
                    <div>
                      <span className="text-muted-foreground">Adds guardrails: </span>
                      {m.guardrailsAdded.join(' · ')}
                    </div>
                  )}
                  <div className="text-muted-foreground">Adds {m.tokens.toLocaleString('en-CA')} tokens to a turn when it loads.</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Tests</span>
            <LoadingButton variant="outline" size="sm" isLoading={dryRun.isPending} onClick={() => dryRun.mutate({ draft: checkDraft, tests: tests ?? [] }, { onSuccess: setRun, onError: (e) => toast.error('Couldn’t run the tests', { description: e.message }) })} data-testid="gen-run-tests">
              <Play className="size-3.5" /> Run tests now
            </LoadingButton>
          </div>
          {run ? (
            <div className="overflow-hidden rounded-md border" data-testid="gen-run-result">
              <div className={cn('px-3 py-2 text-sm font-medium', run.passed === run.total ? 'bg-success/10 text-success-text' : 'bg-warning/10 text-warning-text')}>
                {run.passed} of {plural(run.total, 'case')} pass
              </div>
              <ul className="divide-y">
                {run.results.map((r) => (
                  <li key={r.caseId} className="flex items-start gap-2 px-3 py-2 text-sm">
                    {r.status === 'pass' ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-text" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />}
                    <div className="min-w-0">
                      <div>{r.caseName}</div>
                      {r.failure && <div className="text-xs text-muted-foreground">{r.failure}</div>}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">Nothing is stored by this run. Requesting review runs them again on the saved version.</p>
          )}
        </section>

        <FormField id="gen-review-note" label="Note for the reviewer" optional hint="Sent with Save and request review.">
          <Textarea id="gen-review-note" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} className="min-h-16" placeholder="e.g. Drafted from twenty resolved cases; replaces the manual checklist." />
        </FormField>
      </div>
    );
  };

  const editing = testDialog?.index != null ? tests?.[testDialog.index] : undefined;
  return (
    <>
      <DialogShell
        open={open}
        onOpenChange={onOpenChange}
        size="xl"
        title="Generate skill"
        description="Drafted by the model through the AI gateway. It is saved as a draft and needs a reviewer before any agent can use it."
        headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="gen-stepper" />}
        panelClassName="h-[min(85vh,820px)]"
        bodyRef={bodyRef}
        data-testid="generate-skill-dialog"
        footer={
          <div className="flex w-full items-center gap-2">
            <span className="mr-auto text-xs text-muted-foreground">
              Step {step} of {STEPS.length}
              {saveError && <span className="ml-2 text-destructive">{saveError}</span>}
            </span>
            {step > 1 && (
              <Button variant="outline" onClick={() => go(step - 1)} disabled={create.isPending}>
                Back
              </Button>
            )}
            {step < STEPS.length ? (
              <Button onClick={next} data-testid="gen-next" disabled={options.isPending || options.isError}>
                Next
              </Button>
            ) : (
              <>
                <LoadingButton variant="outline" isLoading={create.isPending && !create.variables?.requestReview} disabled={create.isPending} onClick={() => save(false)} data-testid="gen-save-draft">
                  Save as draft
                </LoadingButton>
                <LoadingButton isLoading={create.isPending && !!create.variables?.requestReview} disabled={create.isPending} onClick={() => save(true)} data-testid="gen-save-review">
                  Save and request review
                </LoadingButton>
              </>
            )}
          </div>
        }
      >
        {body()}
      </DialogShell>
      <SkillTestDialog
        open={!!testDialog}
        onOpenChange={(o) => !o && setTestDialog(null)}
        initial={editing}
        tools={(opts?.tools ?? []).filter((t) => draft.toolIds.includes(t.toolId)).map((t) => t.name)}
        knowledgeBases={draft.knowledgeBases}
        onSubmit={(t) => {
          setTests((xs) => (testDialog?.index != null ? (xs ?? []).map((x, j) => (j === testDialog.index ? t : x)) : [...(xs ?? []), { ...t, source: 'manual' }]));
        }}
      />
    </>
  );
}
