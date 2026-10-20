'use client';

import * as React from 'react';
import { AlertCircle, AlertTriangle, CheckCircle2, GitCompare, Loader2, Pencil, Plus, RotateCcw, Sparkles, Square, Wand2, X } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { Stepper } from '@/components/shared/stepper';
import { TagInput } from '@/components/shared/tag-input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import type { PromptGeneratorBackend } from '@/hooks/prompt-queries';
import { plural } from '@/lib/format';
import { composeInstructions } from '@/lib/prompts';
import type { AgentGuardrails } from '@/lib/types/domain';
import type { OutputFormat, PromptContext, PromptLintFinding, PromptSection, PromptSpec } from '@/lib/types/prompts';
import { cn } from '@/lib/utils';

import { ListField } from './list-field';
import { PromptDiff } from './prompt-diff';

const STEPS = ['Purpose', 'Behaviour', 'Process', 'Tools and knowledge', 'Compliance', 'Output', 'Generate'] as const;
const STAFF_ROLES = ['Servicing agents', 'Branch staff', 'Contact-centre agents', 'Fraud analysts', 'Underwriters', 'Compliance officers', 'Collections officers', 'Operations managers', 'All staff'];
const TONES = ['Professional and warm', 'Neutral and precise', 'Plain and friendly', 'Formal'];
const READING = ['Grade 6', 'Grade 8', 'Grade 10', 'Professional'];
const UNSURE: Record<AgentGuardrails['whenUnsure'], string> = { handoff: 'Hand to a person', ask: 'Ask one clarifying question', decline: 'Decline and explain why' };
const FORMATS: Record<OutputFormat, string> = { email: 'Email', chat: 'Chat reply', bullets: 'Bullet summary', memo: 'Internal memo', json: 'JSON' };
const DEFAULT_CITATION = 'Always cite the knowledge base and section behind every policy statement.';

/** A starting spec from what the agent or template already says, so the builder never opens empty. */
export function initialSpec(from: { role: string; channels: string[]; tools: string[]; collections: string[]; guardrails: AgentGuardrails; toolHints?: Record<string, string> }): PromptSpec {
  return {
    purpose: { role: from.role, serves: '', goals: [''], outOfScope: from.guardrails.blockedTopics.length ? [...from.guardrails.blockedTopics] : [''] },
    behaviour: { tone: TONES[0], readingLevel: 'Grade 8', languages: ['English'], verbosity: 'standard', whenUnsure: from.guardrails.whenUnsure, escalationTriggers: [''] },
    process: { steps: [''], decisionRules: [''], requiredChecks: [''] },
    toolsKnowledge: { toolUse: from.tools.map((t) => ({ tool: t, when: from.toolHints?.[t]?.replace(/^./, (c) => c.toLowerCase()) ?? '' })), knowledge: from.collections, citationRule: from.collections.length ? DEFAULT_CITATION : '', neverWithTools: [''] },
    compliance: { disclosures: [''], forbiddenPhrases: [], piiHandling: from.guardrails.redactPii ? 'Show only the last four digits of any account, card or SIN.' : '', regulatoryNotes: '' },
    output: { format: from.channels.includes('email') ? 'email' : 'chat', structure: '', variables: [], examples: [] },
  };
}

const filled = (xs: string[]) => xs.filter((x) => x.trim()).length;

/**
 * Writes agent instructions from grouped feature fields. Generation streams through the AI gateway; the result
 * is linted against the agent's real grants and variables, can be rewritten per section and compared with the
 * current instructions, and Apply only writes the field. Saving the agent is a separate, re-test change.
 */
export function PromptGeneratorDialog({
  open,
  onOpenChange,
  backend,
  context,
  initial,
  currentInstructions,
  onApply,
  applyNote,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  backend: PromptGeneratorBackend;
  context: PromptContext;
  initial: PromptSpec;
  currentInstructions: string;
  onApply: (text: string) => void;
  /** What applying does where the dialog was opened, e.g. "Save as v8 to run evals". */
  applyNote: string;
}) {
  const [step, setStep] = React.useState(1);
  const [spec, setSpec] = React.useState<PromptSpec>(initial);
  const [touched, setTouched] = React.useState(false);
  const [generatedFor, setGeneratedFor] = React.useState<string | null>(null);
  const [compare, setCompare] = React.useState(false);
  const [rewriting, setRewriting] = React.useState<{ id: string; text: string; error?: string } | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const bodyRef = React.useRef<HTMLDivElement>(null);
  const { generation: g } = backend;

  React.useEffect(() => {
    if (!open) return;
    setStep(1);
    setSpec(initial);
    setTouched(false);
    setGeneratedFor(null);
    setCompare(false);
    setRewriting(null);
    setActionError(null);
    // Reset only when the dialog opens: callers rebuild `initial` on every render.
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);

  const put = <K extends keyof PromptSpec>(k: K, patch: Partial<PromptSpec[K]>) => setSpec((s) => ({ ...s, [k]: { ...s[k], ...patch } }));
  const varKeys = backend.variables.map((v) => v.key);
  const unknownVars = spec.output.variables.filter((v) => !varKeys.includes(v.replace(/^\{|\}$/g, '')));
  const errors: Partial<Record<string, string>> = {
    role: spec.purpose.role.trim().length < 3 ? 'Describe the role in a few words, e.g. Drafts replies to hardship emails.' : undefined,
    goals: filled(spec.purpose.goals) ? undefined : 'Add at least one goal.',
    tone: spec.behaviour.tone.trim() ? undefined : 'Choose or write a tone.',
    languages: spec.behaviour.languages.length ? undefined : 'Add at least one language.',
    steps: filled(spec.process.steps) ? undefined : 'Add at least one step. The model follows them in order.',
    toolUse: spec.toolsKnowledge.toolUse.some((t) => t.tool && !t.when.trim()) ? 'Say when to use each tool.' : undefined,
    variables: unknownVars.length ? `${unknownVars.map((v) => `{${v}}`).join(', ')} ${unknownVars.length === 1 ? 'is not a variable' : 'are not variables'} the runtime can fill.` : undefined,
    examples: spec.output.examples.some((e) => !!e.input.trim() !== !!e.output.trim()) ? 'Each example needs both an input and an output.' : undefined,
  };
  const STEP_FIELDS: Record<number, string[]> = { 1: ['role', 'goals'], 2: ['tone', 'languages'], 3: ['steps'], 4: ['toolUse'], 5: [], 6: ['variables', 'examples'], 7: [] };
  const err = (k: string) => (touched ? errors[k] : undefined);
  const stepValid = (n: number) => STEP_FIELDS[n].every((k) => !errors[k]);

  const specKey = JSON.stringify(spec);
  const run = () => {
    setGeneratedFor(specKey);
    setCompare(false);
    setRewriting(null);
    void g.start(spec, context);
  };
  const next = () => {
    if (!stepValid(step)) return setTouched(true);
    setTouched(false);
    const to = step + 1;
    setStep(to);
    if (to === STEPS.length && generatedFor !== specKey) run();
  };

  const text = composeInstructions(g.sections);
  const findings = g.analysis?.findings ?? [];
  const blocking = findings.filter((f) => f.severity === 'error');
  const streaming = g.status === 'streaming';

  /** Fixes and rewrites change one section, then the whole prompt is re-checked so the lint panel stays true. */
  const replaceSection = async (id: string, body: string) => {
    const nextSections = g.sections.map((s) => (s.id === id ? { ...s, body } : s));
    g.setSections(nextSections);
    setActionError(null);
    try {
      g.setAnalysis(await backend.analyze(nextSections, context));
    } catch (e) {
      setActionError((e as Error).message);
    }
  };
  const applyFix = (f: PromptLintFinding) => f.fix && void replaceSection(f.fix.sectionId, f.fix.body);
  const submitRewrite = async (section: PromptSection) => {
    if (!rewriting?.text.trim()) return setRewriting((r) => r && { ...r, error: 'Say how to rewrite it, e.g. Shorter, or As bullets.' });
    try {
      const out = await backend.rewrite({ section, instruction: rewriting.text, context });
      setRewriting(null);
      await replaceSection(section.id, out.body);
    } catch (e) {
      setRewriting((r) => r && { ...r, error: (e as Error).message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={(o) => {
        if (!o && streaming) g.stop();
        onOpenChange(o);
      }}
      size="xl"
      title="Generate instructions"
      description={`Step ${step} of ${STEPS.length} · ${STEPS[step - 1]}`}
      headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="generator-stepper" />}
      bodyRef={bodyRef}
      bodyClassName="h-[30rem]"
      data-testid="prompt-generator"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <Button variant="ghost" onClick={() => (step === 1 ? onOpenChange(false) : (streaming && g.stop(), setStep(step - 1)))}>
            {step === 1 ? 'Cancel' : 'Back'}
          </Button>
          {step < STEPS.length ? (
            <Button onClick={next}>{step === STEPS.length - 1 ? 'Generate' : 'Next'}</Button>
          ) : (
            <div className="flex items-center gap-3">
              {blocking.length > 0 && !streaming && <span className="text-xs text-destructive">Fix {plural(blocking.length, 'error')} before applying</span>}
              <Button
                disabled={streaming || !g.sections.length || blocking.length > 0 || backend.busy}
                onClick={() => {
                  onApply(text);
                  onOpenChange(false);
                }}
                data-testid="apply-instructions"
              >
                Apply to instructions
              </Button>
            </div>
          )}
        </div>
      }
    >
      {step === 1 && (
        <div className="flex flex-col gap-4">
          <FormField id="pg-role" label="Role" error={err('role')} hint="One line. The agent introduces itself this way to the model.">
            <Input id="pg-role" value={spec.purpose.role} onChange={(e) => put('purpose', { role: e.target.value })} placeholder="e.g. Drafts replies to hardship emails" aria-invalid={!!err('role')} autoFocus />
          </FormField>
          <FormField id="pg-serves" label="Who it serves" optional hint="The staff role that reads its output.">
            <Select value={spec.purpose.serves} onValueChange={(v) => put('purpose', { serves: v })}>
              <SelectTrigger id="pg-serves" className="w-full">
                <SelectValue placeholder="Choose a staff role" />
              </SelectTrigger>
              <SelectContent>
                {STAFF_ROLES.map((r) => (
                  <SelectItem key={r} value={r}>
                    {r}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <div className="grid gap-4 md:grid-cols-2">
            <FormField id="pg-goals" label="Primary goals" error={err('goals')}>
              <ListField id="pg-goals" value={spec.purpose.goals} onChange={(v) => put('purpose', { goals: v })} placeholder="e.g. Answer the customer’s question in the first paragraph" addLabel="Add goal" invalid={!!err('goals')} />
            </FormField>
            <FormField id="pg-oos" label="Out of scope" optional>
              <ListField id="pg-oos" value={spec.purpose.outOfScope} onChange={(v) => put('purpose', { outOfScope: v })} placeholder="e.g. Investment advice" addLabel="Add topic" />
            </FormField>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 md:grid-cols-2">
            <FormField id="pg-tone" label="Tone" error={err('tone')}>
              <Select value={TONES.includes(spec.behaviour.tone) ? spec.behaviour.tone : 'custom'} onValueChange={(v) => put('behaviour', { tone: v === 'custom' ? '' : v })}>
                <SelectTrigger id="pg-tone" className="w-full" aria-invalid={!!err('tone')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TONES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                  <SelectItem value="custom">Custom…</SelectItem>
                </SelectContent>
              </Select>
              {!TONES.includes(spec.behaviour.tone) && <Input value={spec.behaviour.tone} onChange={(e) => put('behaviour', { tone: e.target.value })} placeholder="e.g. Calm and reassuring, never casual" aria-label="Custom tone" />}
            </FormField>
            <FormField id="pg-reading" label="Reading level">
              <Select value={spec.behaviour.readingLevel} onValueChange={(v) => put('behaviour', { readingLevel: v })}>
                <SelectTrigger id="pg-reading" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {READING.map((r) => (
                    <SelectItem key={r} value={r}>
                      {r}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="pg-lang" label="Languages" error={err('languages')} hint="It replies in the customer’s language when it is on this list.">
              <TagInput id="pg-lang" value={spec.behaviour.languages} onChange={(v) => put('behaviour', { languages: v })} suggestions={['English', 'French', 'Spanish', 'Punjabi', 'Mandarin']} placeholder="Add a language" />
            </FormField>
            <FormField id="pg-length" label="Length">
              <ToggleGroup id="pg-length" type="single" variant="outline" value={spec.behaviour.verbosity} onValueChange={(v) => v && put('behaviour', { verbosity: v as PromptSpec['behaviour']['verbosity'] })} className="w-full">
                <ToggleGroupItem value="brief" className="flex-1">
                  Brief
                </ToggleGroupItem>
                <ToggleGroupItem value="standard" className="flex-1">
                  Standard
                </ToggleGroupItem>
                <ToggleGroupItem value="detailed" className="flex-1">
                  Detailed
                </ToggleGroupItem>
              </ToggleGroup>
            </FormField>
            <FormField id="pg-unsure" label="When unsure">
              <Select value={spec.behaviour.whenUnsure} onValueChange={(v) => put('behaviour', { whenUnsure: v as AgentGuardrails['whenUnsure'] })}>
                <SelectTrigger id="pg-unsure" className="w-full">
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
          </div>
          <FormField id="pg-esc" label="Escalation triggers" optional hint="Situations where it always hands to a person.">
            <ListField id="pg-esc" value={spec.behaviour.escalationTriggers} onChange={(v) => put('behaviour', { escalationTriggers: v })} placeholder="e.g. The customer mentions a death, illness or job loss" addLabel="Add trigger" />
          </FormField>
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          <FormField id="pg-steps" label="Procedure" error={err('steps')} hint="Press Enter for the next step.">
            <ListField id="pg-steps" value={spec.process.steps} onChange={(v) => put('process', { steps: v })} placeholder="e.g. Read the whole email before choosing an intent" addLabel="Add step" numbered invalid={!!err('steps')} />
          </FormField>
          <div className="grid gap-4 md:grid-cols-2">
            <FormField id="pg-rules" label="Decision rules" optional hint="Start with Always or Never so conflicts can be found.">
              <ListField id="pg-rules" value={spec.process.decisionRules} onChange={(v) => put('process', { decisionRules: v })} placeholder="e.g. Always offer the hardship line first" addLabel="Add rule" />
            </FormField>
            <FormField id="pg-checks" label="Required checks before acting" optional>
              <ListField id="pg-checks" value={spec.process.requiredChecks} onChange={(v) => put('process', { requiredChecks: v })} placeholder="e.g. The account number matches the case" addLabel="Add check" />
            </FormField>
          </div>
        </div>
      )}

      {step === 4 && (
        <div className="flex flex-col gap-4">
          <FormField id="pg-tools" label="When to use each tool" error={err('toolUse')} hint="Only operations this agent is granted are listed.">
            {context.grantedTools.length === 0 ? (
              <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">No tools granted, so the instructions will not mention any. Grant tools on the agent first.</p>
            ) : (
              <div className="flex flex-col gap-1.5">
                {spec.toolsKnowledge.toolUse.map((t, i) => (
                  <div key={i} className="grid grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto] items-center gap-1.5">
                    <Select value={t.tool} onValueChange={(v) => put('toolsKnowledge', { toolUse: spec.toolsKnowledge.toolUse.map((x, j) => (j === i ? { ...x, tool: v } : x)) })}>
                      <SelectTrigger className="w-full font-mono text-xs" aria-label={`Tool ${i + 1}`}>
                        <SelectValue placeholder="Choose a tool" />
                      </SelectTrigger>
                      <SelectContent>
                        {context.grantedTools.map((n) => (
                          <SelectItem key={n} value={n} className="font-mono text-xs">
                            {n}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Input
                      value={t.when}
                      onChange={(e) => put('toolsKnowledge', { toolUse: spec.toolsKnowledge.toolUse.map((x, j) => (j === i ? { ...x, when: e.target.value } : x)) })}
                      placeholder="e.g. the email names a loan number"
                      aria-label={`When to use tool ${i + 1}`}
                      aria-invalid={!!err('toolUse') && !!t.tool && !t.when.trim()}
                    />
                    <Button variant="ghost" size="icon" className="size-8" aria-label={`Remove tool ${i + 1}`} onClick={() => put('toolsKnowledge', { toolUse: spec.toolsKnowledge.toolUse.filter((_, j) => j !== i) })}>
                      <X className="size-3.5" />
                    </Button>
                  </div>
                ))}
                <Button variant="ghost" size="sm" className="self-start" onClick={() => put('toolsKnowledge', { toolUse: [...spec.toolsKnowledge.toolUse, { tool: '', when: '' }] })}>
                  <Plus className="size-3.5" /> Add tool
                </Button>
              </div>
            )}
          </FormField>
          <div className="grid gap-4 md:grid-cols-2">
            <FormField id="pg-kb" label="Knowledge bases to search" optional hint={context.collections.length ? 'The agent’s attached knowledge bases.' : 'No knowledge attached to this agent.'}>
              <div className="flex flex-col gap-1.5">
                {context.collections.map((k) => (
                  <label key={k} className="flex items-center gap-2 text-sm">
                    <Checkbox checked={spec.toolsKnowledge.knowledge.includes(k)} onCheckedChange={(c) => put('toolsKnowledge', { knowledge: c ? [...spec.toolsKnowledge.knowledge, k] : spec.toolsKnowledge.knowledge.filter((x) => x !== k) })} />
                    {k}
                  </label>
                ))}
              </div>
            </FormField>
            <FormField id="pg-cite" label="Citation rule" optional hint="Model Risk expects a citation for every policy statement.">
              <Textarea id="pg-cite" rows={2} value={spec.toolsKnowledge.citationRule} onChange={(e) => put('toolsKnowledge', { citationRule: e.target.value })} placeholder="e.g. Always cite the policy section" />
            </FormField>
          </div>
          <FormField id="pg-never" label="Never do with tools" optional>
            <ListField id="pg-never" value={spec.toolsKnowledge.neverWithTools} onChange={(v) => put('toolsKnowledge', { neverWithTools: v })} placeholder="e.g. Never call a write tool twice for the same case" addLabel="Add rule" />
          </FormField>
        </div>
      )}

      {step === 5 && (
        <div className="flex flex-col gap-4">
          <p className="text-xs text-muted-foreground" data-testid="generator-always-on-note">
            Shared wording such as the bank disclosure, the tone guide or the citation rule is not written here: attach it as an always-on skill under Skills on the agent, so its owner keeps the wording.
          </p>
          <div className="grid gap-4 md:grid-cols-2">
            <FormField id="pg-disc" label="Required disclosures or phrases" optional>
              <ListField id="pg-disc" value={spec.compliance.disclosures} onChange={(v) => put('compliance', { disclosures: v })} placeholder="e.g. You can ask us to contact you in writing only." addLabel="Add phrase" />
            </FormField>
            <FormField id="pg-forbid" label="Forbidden phrases" optional>
              <TagInput id="pg-forbid" value={spec.compliance.forbiddenPhrases} onChange={(v) => put('compliance', { forbiddenPhrases: v })} suggestions={['guaranteed approval', 'risk-free', 'final notice', 'we will sue']} placeholder="e.g. guaranteed approval" />
            </FormField>
            <FormField id="pg-pii" label="Personal data handling" optional>
              <Textarea id="pg-pii" rows={2} value={spec.compliance.piiHandling} onChange={(e) => put('compliance', { piiHandling: e.target.value })} placeholder="e.g. Show only the last four digits" />
            </FormField>
            <FormField id="pg-reg" label="Regulatory notes" optional>
              <Textarea id="pg-reg" rows={2} value={spec.compliance.regulatoryNotes} onChange={(e) => put('compliance', { regulatoryNotes: e.target.value })} placeholder="e.g. Follow the provincial collection agency rules on contact hours" />
            </FormField>
          </div>
        </div>
      )}

      {step === 6 && (
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 md:grid-cols-2">
            <FormField id="pg-format" label="Format">
              <Select value={spec.output.format} onValueChange={(v) => put('output', { format: v as OutputFormat })}>
                <SelectTrigger id="pg-format" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(FORMATS).map(([v, l]) => (
                    <SelectItem key={v} value={v}>
                      {l}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField id="pg-vars" label="Variables to fill" optional error={err('variables')} hint={errors.variables ?? 'The runtime fills these from the case and the signed-in user.'}>
              <TagInput id="pg-vars" value={spec.output.variables} onChange={(v) => put('output', { variables: v.map((x) => x.replace(/^\{|\}$/g, '')) })} suggestions={varKeys} format={(k) => `{${k}}`} placeholder="e.g. customer.first_name" />
            </FormField>
          </div>
          <FormField id="pg-structure" label="Structure" optional hint={spec.output.format === 'json' ? 'Paste the JSON schema or list the keys.' : 'Headings, order of paragraphs, sign-off.'}>
            <Textarea id="pg-structure" rows={3} value={spec.output.structure} onChange={(e) => put('output', { structure: e.target.value })} placeholder="e.g. Answer first, then the next step, then the sign-off" />
          </FormField>
          <FormField id="pg-ex" label="Examples" optional error={err('examples')} hint="Input and output pairs. Two good examples beat ten rules.">
            <div className="flex flex-col gap-2">
              {spec.output.examples.map((ex, i) => (
                <div key={i} className="grid gap-1.5 rounded-md border p-2 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
                  <Textarea rows={2} value={ex.input} onChange={(e) => put('output', { examples: spec.output.examples.map((x, j) => (j === i ? { ...x, input: e.target.value } : x)) })} placeholder="e.g. Can you waive my late fee?" aria-label={`Example ${i + 1} input`} />
                  <Textarea rows={2} value={ex.output} onChange={(e) => put('output', { examples: spec.output.examples.map((x, j) => (j === i ? { ...x, output: e.target.value } : x)) })} placeholder="e.g. Hi Dana, we can waive one late fee a year…" aria-label={`Example ${i + 1} output`} />
                  <Button variant="ghost" size="icon" className="size-8" aria-label={`Remove example ${i + 1}`} onClick={() => put('output', { examples: spec.output.examples.filter((_, j) => j !== i) })}>
                    <X className="size-3.5" />
                  </Button>
                </div>
              ))}
              <Button variant="ghost" size="sm" className="self-start" onClick={() => put('output', { examples: [...spec.output.examples, { input: '', output: '' }] })}>
                <Plus className="size-3.5" /> Add example
              </Button>
            </div>
          </FormField>
        </div>
      )}

      {step === 7 && (
        <div className="grid h-full gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="flex min-h-0 flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              {streaming ? (
                <Button size="sm" variant="outline" onClick={g.stop} data-testid="stop-generation">
                  <Square className="size-3.5" /> Stop
                </Button>
              ) : (
                <Button size="sm" variant="outline" onClick={run} data-testid="regenerate">
                  <RotateCcw className="size-3.5" /> Regenerate
                </Button>
              )}
              <Button size="sm" variant={compare ? 'secondary' : 'ghost'} onClick={() => setCompare((c) => !c)} disabled={streaming || !g.sections.length} data-testid="compare-toggle">
                <GitCompare className="size-3.5" /> {compare ? 'Show sections' : 'Compare with current'}
              </Button>
              <span className="ml-auto text-xs text-muted-foreground tabular-nums" data-testid="token-estimate">
                {streaming ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 className="size-3.5 animate-spin" /> Generating…
                  </span>
                ) : g.analysis ? (
                  `${g.analysis.tokens.toLocaleString()} tokens · ≈ $${g.analysis.costPer1kRunsUsd.toFixed(2)} per 1,000 runs on ${context.model}`
                ) : g.status === 'stopped' ? (
                  'Stopped. Regenerate to finish.'
                ) : null}
              </span>
            </div>
            {g.status === 'error' && (
              <p className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                <AlertCircle className="mt-0.5 size-4 shrink-0" /> {g.error}
              </p>
            )}
            {actionError && <p className="text-xs text-destructive">{actionError}</p>}
            {compare ? (
              <PromptDiff before={currentInstructions} after={text} />
            ) : (
              <div className="flex flex-col gap-3" data-testid="generated-sections">
                {g.sections.length === 0 && streaming && <p className="text-sm text-muted-foreground">Sending your fields to the prompt builder…</p>}
                {g.sections.map((s) => (
                  <section key={s.id} className="rounded-lg border" data-section={s.id}>
                    <header className="flex items-center justify-between border-b px-3 py-1.5">
                      <h3 className="text-sm font-medium">{s.title}</h3>
                      <Button variant="ghost" size="sm" className="h-7" disabled={streaming || backend.busy} onClick={() => setRewriting({ id: s.id, text: '' })}>
                        <Pencil className="size-3.5" /> Rewrite
                      </Button>
                    </header>
                    <pre className="px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap">{s.body}</pre>
                    {rewriting?.id === s.id && (
                      <form
                        className="flex flex-col gap-1 border-t bg-muted/30 px-3 py-2"
                        onSubmit={(e) => {
                          e.preventDefault();
                          void submitRewrite(s);
                        }}
                      >
                        <div className="flex gap-2">
                          <Input autoFocus value={rewriting.text} onChange={(e) => setRewriting({ id: s.id, text: e.target.value })} placeholder="e.g. Shorter, or As bullets" aria-label={`How to rewrite ${s.title}`} aria-invalid={!!rewriting.error} />
                          <Button type="submit" size="sm" disabled={backend.busy}>
                            {backend.busy ? <Loader2 className="size-3.5 animate-spin" /> : <Wand2 className="size-3.5" />} Rewrite
                          </Button>
                          <Button type="button" size="sm" variant="ghost" onClick={() => setRewriting(null)}>
                            Cancel
                          </Button>
                        </div>
                        {rewriting.error && <p className="text-xs text-destructive">{rewriting.error}</p>}
                      </form>
                    )}
                  </section>
                ))}
              </div>
            )}
          </div>
          <aside className="flex min-h-0 flex-col gap-2 rounded-lg border p-3" aria-label="Lint" data-testid="lint-panel">
            <h3 className="flex items-center gap-1.5 text-sm font-medium">
              <Sparkles className="size-4 text-muted-foreground" /> Checks
            </h3>
            {streaming || !g.analysis ? (
              <p className="text-xs text-muted-foreground">{streaming ? 'Checks run when generation finishes.' : 'No checks yet.'}</p>
            ) : findings.length === 0 ? (
              <p className="flex items-center gap-1.5 text-sm text-success-text">
                <CheckCircle2 className="size-4" /> No problems found
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {findings.map((f) => (
                  <li key={f.id} className={cn('rounded-md border p-2 text-xs', f.severity === 'error' ? 'border-destructive/30 bg-destructive/5' : 'border-warning/40 bg-warning/5')} data-rule={f.rule}>
                    <p className="flex items-start gap-1.5">
                      {f.severity === 'error' ? <AlertCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" /> : <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning-text" />}
                      <span>{f.message}</span>
                    </p>
                    {f.fix && (
                      <Button size="sm" variant="outline" className="mt-1.5 h-auto min-h-7 max-w-full bg-card py-1 text-left whitespace-normal" disabled={backend.busy} onClick={() => applyFix(f)}>
                        {f.fix.label}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-auto pt-2 text-xs text-muted-foreground">{applyNote}</p>
          </aside>
        </div>
      )}
    </DialogShell>
  );
}
