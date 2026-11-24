'use client';

import * as React from 'react';
import { AlertTriangle, ChevronDown, FlaskConical, Trash2 } from 'lucide-react';

import { TryPanel } from '@/components/agents/try-panel';
import { DetailSheet } from '@/components/shared/detail-sheet';
import { FormField } from '@/components/shared/form-field';
import { QueryError } from '@/components/shared/query-states';
import { KeyValues, Section } from '@/components/shared/surface';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { useStepSample } from '@/hooks/engine-queries';
import type { DefinitionCheck, EngineNode, EngineNodeType, SampleStep } from '@/lib/types/engine';

import { groupLook } from './definition-node';
import { type FieldSource, FieldSourceContext, SAVE_FIRST } from './field-picker';
import { NodeSettingsForm, type StepRefs } from './node-form';
import { HowItStarts } from './trigger-panels';

const EXTRACT = 'ops.ai.extract';
const TOOL_STEP = 'ops.action.tool';
/** The kind of step in a builder's words, by the type's group. */
const KIND: Record<string, string> = { trigger: 'Starts the workflow', data: 'Works with data', flow: 'Controls the flow', action: 'Does something in an app', ai: 'Uses AI', human: 'Asks a person' };
const pretty = (p: Record<string, unknown> | undefined) => JSON.stringify(p ?? {}, null, 2);

export interface StepSheetProps {
  node: EngineNode | null;
  type: EngineNodeType | undefined;
  workflowId: string;
  steps: StepRefs;
  /** The server's checks about this step. */
  checks: DefinitionCheck[];
  /** Steps in the order they run; previous and next walk it. */
  order: string[];
  readOnly: boolean;
  /** The digest of the working copy as last saved: What it receives is read again once a save lands. */
  savedDigest?: string;
  onClose: () => void;
  onMove: (id: string) => void;
  onChange: (patch: Partial<Pick<EngineNode, 'name' | 'parameters'>>) => void;
  onDelete: () => void;
}

/** Brings the field a problem names into view and focuses it. */
function fixField(nodeId: string, field: string | null | undefined) {
  const id = field ? `node-${nodeId}-${field}` : 'definition-node-name';
  const el = document.getElementById(id) ?? document.querySelector<HTMLElement>(`[data-field="${id}"]`);
  el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  el?.focus({ preventScroll: true });
}

/**
 * A step's settings in a sheet beside the canvas, top to bottom: its name and what it does in plain words, Problems
 * with Fix, How it starts (trigger steps only; see trigger-panels.tsx), What it receives, Settings, When it fails,
 * What it gives, and Try step for a tool step. The sheet is not modal, so the canvas stays usable and clicking another
 * step moves the sheet to it. Edits change the editor's draft as they are made; the working copy saves itself.
 */
export function StepSheet({ node, type, workflowId, steps, checks, order, readOnly, savedDigest = '', onClose, onMove, onChange, onDelete }: StepSheetProps) {
  const index = node ? order.indexOf(node.id) : -1;
  const errors = checks.filter((c) => c.level === 'error');
  const byField = Object.fromEntries(errors.filter((c) => c.field).map((c) => [c.field as string, c.message]));
  const look = groupLook(type?.group, node?.type);
  const trigger = type?.group === 'trigger';
  const installed = !!type;
  const locked = readOnly || !installed;
  const sample = useStepSample(workflowId, node?.id, savedDigest);
  const names = React.useMemo(() => Object.fromEntries(steps.all.map((s) => [s.id, s.label])), [steps.all]);
  const source: FieldSource = {
    steps: sample.data?.steps ?? [],
    loading: sample.isLoading,
    unsaved: sample.data ? !sample.data.saved : false,
    names: node ? { ...names, [node.id]: node.name || type?.label || '' } : names,
    readOnly: locked,
  };
  return (
    <DetailSheet
      open={!!node}
      onOpenChange={(o) => !o && onClose()}
      modal={false}
      // Starts at the canvas's top edge (--step-sheet-top, set by the editor) so Save version and Test run stay in view.
      widthClass="sm:max-w-xl sm:top-[var(--step-sheet-top,0px)] sm:h-[calc(100dvh-var(--step-sheet-top,0px))]"
      testId="step-sheet"
      scrollKey={node?.id}
      title={node ? node.name || type?.label || 'Step' : ''}
      description={type ? type.summary || type.description : node ? "This step's type is not installed." : undefined}
      tags={
        node && (
          <>
            <Badge variant="outline" className={look.tile}>
              {type ? `${type.label} · ${KIND[type.group] ?? type.group}` : 'Not installed'}
            </Badge>
            {errors.length > 0 && <Badge variant="destructive">{errors.length === 1 ? '1 problem' : `${errors.length} problems`}</Badge>}
          </>
        )
      }
      navigation={
        index >= 0
          ? {
              currentIndex: index,
              totalCount: order.length,
              onPrev: index > 0 ? () => onMove(order[index - 1]) : undefined,
              onNext: index < order.length - 1 ? () => onMove(order[index + 1]) : undefined,
            }
          : undefined
      }
      footerActions={
        node &&
        !readOnly && (
          <Button type="button" variant="ghost" size="sm" className="text-destructive-text" onClick={onDelete} data-testid="definition-node-delete">
            <Trash2 /> Delete step
          </Button>
        )
      }
    >
      {node && (
        <FieldSourceContext.Provider value={source}>
          <div className="flex min-w-0 flex-col gap-6" data-testid="step-sheet-body">
            {type?.how && <HowThisStepWorks text={type.how} />}
            {!installed && (
              <Alert data-testid="step-not-installed">
                <AlertTriangle />
                <AlertTitle>This step&apos;s type is not installed</AlertTitle>
                <AlertDescription>Its settings are shown read-only. Install the plugin that adds it, or delete the step.</AlertDescription>
              </Alert>
            )}
            {errors.length > 0 && (
              <Alert variant="destructive" data-testid="step-sheet-errors">
                <AlertTriangle />
                <AlertTitle>Fix before you publish</AlertTitle>
                <AlertDescription>
                  <ul className="flex w-full flex-col gap-2">
                    {errors.map((c, i) => (
                      <li key={`${c.code}-${i}`} className="flex min-w-0 items-start justify-between gap-2">
                        <span className="min-w-0">{c.message}</span>
                        {!locked && (
                          <Button type="button" variant="outline" size="sm" onClick={() => fixField(node.id, c.field)} data-testid="step-problem-fix">
                            Fix
                          </Button>
                        )}
                      </li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}
            {trigger && (
              <fieldset disabled={locked} className="min-w-0">
                <HowItStarts node={node} workflowId={workflowId} readOnly={locked} onChange={(parameters) => onChange({ parameters })} />
              </fieldset>
            )}
            {!trigger && <WhatItReceives sample={sample} />}
            <div data-testid="step-settings">
              <Section title="Settings">
                {/* Keyed by node id so moving to another step resets the field drafts. */}
                <fieldset disabled={locked} className="flex min-w-0 flex-col gap-4">
                  <StepFields key={node.id} node={node} type={type} steps={steps} errors={byField} onChange={onChange} />
                </fieldset>
              </Section>
            </div>
            {type && <WhenItFails type={type} parameters={node.parameters ?? {}} />}
            <WhatItGives given={sample.data?.given ?? null} loading={sample.isLoading} unsaved={source.unsaved} />
          </div>
        </FieldSourceContext.Provider>
      )}
      {node && node.type === TOOL_STEP && !readOnly && <TryThisStep key={node.id} workflowId={workflowId} nodeId={node.id} />}
    </DetailSheet>
  );
}

function HowThisStepWorks({ text }: { text: string }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen} data-testid="step-how-it-works">
      <CollapsibleTrigger asChild>
        <Button type="button" variant="ghost" size="sm" className="-ml-2" aria-label="How this step works" data-testid="step-how-it-works-open">
          <ChevronDown className={open ? '' : '-rotate-90'} /> Learn more
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2 text-sm text-muted-foreground">{text}</CollapsibleContent>
    </Collapsible>
  );
}

function SampleRows({ step }: { step: SampleStep }) {
  if (step.fields.length === 0) return <p className="text-sm text-muted-foreground">Gives no named fields.</p>;
  return <KeyValues rows={step.fields.map((f) => [f.label, f.sample === null ? <span className="text-muted-foreground">No value</span> : <span className="break-words">{f.sample}</span>])} />;
}

function SampleSkeleton({ testId }: { testId: string }) {
  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="h-4 w-1/3" />
    </div>
  );
}

/** Each earlier step's fields with the last run's values, as the server joined them; fails or loads on its own. */
function WhatItReceives({ sample }: { sample: ReturnType<typeof useStepSample> }) {
  const data = sample.data;
  let body: React.ReactNode;
  if (sample.isLoading) body = <SampleSkeleton testId="step-receives-loading" />;
  else if (sample.isError) body = <QueryError what="what this step receives" error={sample.error} onRetry={() => void sample.refetch()} retrying={sample.isFetching} testId="step-receives-error" />;
  else if (data && !data.saved) body = <p className="text-sm text-muted-foreground">{SAVE_FIRST}</p>;
  else if (data && data.steps.length === 0) body = <p className="text-sm text-muted-foreground">This is the first step. Nothing runs before it.</p>;
  else if (data)
    body = (
      <div className="flex min-w-0 flex-col gap-4">
        {!data.run && <p className="text-sm text-muted-foreground" data-testid="step-receives-no-run">No run yet. Values show after the workflow runs once.</p>}
        {data.steps.map((s) => (
          <div key={s.id} className="flex min-w-0 flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">{s.name}</span>
            <SampleRows step={s} />
          </div>
        ))}
      </div>
    );
  return (
    <div data-testid="step-receives">
      <Section title="What it receives" description="Fields from earlier steps, with your team's last run values.">
        {body}
      </Section>
    </div>
  );
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`;

/** Retries and the time limit in words; the step has no error path to choose. */
function WhenItFails({ type, parameters }: { type: EngineNodeType; parameters: Record<string, unknown> }) {
  const again = Math.max(0, (type.retry?.attempts ?? 1) - 1);
  const timeout = typeof parameters.timeoutSeconds === 'number' ? parameters.timeoutSeconds : type.timeoutSeconds;
  return (
    <div data-testid="step-when-it-fails">
      <Section title="When it fails">
        <KeyValues
          rows={[
            ['Tries again', again === 0 ? 'No. It tries once.' : `Up to ${plural(again, 'more time')}, waiting a little longer each time.`],
            ['If it still fails', 'The run stops as Failed and your team sees it in Runs.'],
            ['Gives up after', `${plural(Math.round(timeout), 'second')} for each try.`],
          ]}
        />
      </Section>
    </div>
  );
}

function WhatItGives({ given, loading, unsaved }: { given: SampleStep | null; loading: boolean; unsaved: boolean }) {
  return (
    <div data-testid="step-what-it-gives">
      <Section title="What it gives" description="What later steps can pick from this step.">
        {loading ? <SampleSkeleton testId="step-gives-loading" /> : unsaved || !given ? <p className="text-sm text-muted-foreground">{SAVE_FIRST}</p> : <SampleRows step={given} />}
      </Section>
    </div>
  );
}

/** Try this one step on the saved working copy, folded until asked for so opening a step reads nothing more. */
function TryThisStep({ workflowId, nodeId }: { workflowId: string; nodeId: string }) {
  const [open, setOpen] = React.useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mt-6 flex flex-col gap-3 border-t pt-4" data-testid="step-try">
      <CollapsibleTrigger asChild>
        <Button type="button" variant="outline" size="sm" className="self-start" data-testid="step-try-open">
          <FlaskConical className="size-4" /> Try step
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p className="mb-3 text-xs text-muted-foreground">Tries the step as last saved. Reads run; a write is shown first and sent only when you confirm.</p>
        {open && <TryPanel target={{ kind: 'workflow_step', workflowId, step: nodeId }} canTry />}
      </CollapsibleContent>
    </Collapsible>
  );
}

function StepFields({
  node,
  type,
  steps,
  errors,
  onChange,
}: {
  node: EngineNode;
  type: EngineNodeType | undefined;
  steps: StepRefs;
  errors: Record<string, string>;
  onChange: (patch: Partial<Pick<EngineNode, 'name' | 'parameters'>>) => void;
}) {
  const [text, setText] = React.useState(() => pretty(node.parameters));
  const [parseError, setParseError] = React.useState<string | undefined>();
  const lastSent = React.useRef(text);
  // A type with no form (an unknown type) can only be edited as JSON, so its settings start open.
  const [allOpen, setAllOpen] = React.useState(!type?.ui?.order.length);

  // Parameters changed outside this field (the form above, or a reload after save) replace the draft text.
  React.useEffect(() => {
    const next = pretty(node.parameters);
    if (next !== pretty(safeParse(lastSent.current))) {
      setText(next);
      lastSent.current = next;
      setParseError(undefined);
    }
  }, [node.parameters]);

  const edit = (value: string) => {
    setText(value);
    let parsed: unknown;
    try {
      parsed = value.trim() ? JSON.parse(value) : {};
    } catch (e) {
      setParseError(e instanceof Error ? e.message : 'Not valid JSON');
      return;
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      setParseError('Parameters must be a JSON object');
      return;
    }
    setParseError(undefined);
    lastSent.current = value;
    onChange({ parameters: parsed as Record<string, unknown> });
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <FormField id="definition-node-name" label="Name" optional>
        <Input id="definition-node-name" value={node.name ?? ''} placeholder={`e.g. ${type?.label ?? 'Review the refund'}`} onChange={(e) => onChange({ name: e.target.value || undefined })} />
      </FormField>
      {type?.ui?.order.length ? (
        <NodeSettingsForm form={type.ui} schema={type.parameters} value={node.parameters ?? {}} steps={steps} idPrefix={`node-${node.id}`}
          errors={errors}
          onChange={(parameters) => onChange({ parameters })}
          testIds={node.type === EXTRACT ? { read: 'step-what-to-read' } : undefined}
        />
      ) : null}
      <Collapsible open={allOpen} onOpenChange={setAllOpen}>
        <CollapsibleTrigger asChild>
          <Button type="button" variant="ghost" size="sm" className="-ml-2 self-start" data-testid="definition-node-all-settings">
            <ChevronDown className={allOpen ? '' : '-rotate-90'} /> All settings
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent className="pt-2">
          <FormField id="definition-node-parameters" label="Parameters as JSON" hint="The same settings as the form above." error={parseError}>
            <Textarea
              id="definition-node-parameters"
              value={text}
              onChange={(e) => edit(e.target.value)}
              spellCheck={false}
              rows={12}
              className="font-mono text-xs"
              aria-invalid={parseError ? true : undefined}
              data-testid="definition-node-parameters"
            />
          </FormField>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

function safeParse(s: string): Record<string, unknown> | undefined {
  try {
    const v: unknown = JSON.parse(s);
    return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : undefined;
  } catch {
    return undefined;
  }
}
