'use client';

import * as React from 'react';
import { NodeViewContent, NodeViewWrapper, useEditorState, type ReactNodeViewProps } from '@tiptap/react';
import { Ban, Braces, Lock, LockOpen, Play, Plus, Search, TriangleAlert, X, type LucideIcon } from 'lucide-react';

import { Selection } from '@tiptap/pm/state';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { PRESET_ICONS } from '@/components/shared/preset-icons';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { PublishBlocker, Ref, RefKind, ReferenceItem } from '@/lib/types/references';

import { cn } from '@/lib/utils';
import { KIND_ICON } from '@/components/shared/reference-kinds';

import { mentionToken } from '@/lib/mentions';
import { type IfNot, chipFor, refsInNode, runsIndex } from './document-model';

export { KIND_ICON };

export interface InvalidField {
  /** A block's key (`brief.purpose`), or `steps`. */
  field: string;
  /** 1-based, with `steps`. */
  step?: number;
  message: string;
}

/** What the document's parts read from the component around them; the editor's own state stays in its tree. */
export interface DocumentContextValue {
  resolved: readonly ReferenceItem[] | undefined;
  missing: readonly PublishBlocker[];
  invalid: readonly InvalidField[];
  /** Lines that do not block a publish, drawn like a problem in the warning colour. */
  warnings: readonly InvalidField[];
  readOnly: boolean;
  /** Removes the block a Remove control on its heading names; left out, no block draws one. */
  removeBlock?: (key: string) => void;
  /** Called with a block's key and the chip picked above its text; left out, no block draws chips. */
  pickChip?: (key: string, text: string) => void;
  /** Set where a missing reference can be given back (the agent page). */
  addBack?: (ref: Ref) => void;
  chooseAnother: (ref: Ref) => void;
  /** Whether the reference at this position stands in a step's sentence, where it can be marked as what the step runs. */
  canMarkRuns: (pos: number) => boolean;
  /** Makes the reference at this position what its step runs, or with null stops the step running it. */
  markRuns: (pos: number, ref: Ref | null) => void;
  /** Locks the tool of the step at this position to that step, or releases it. */
  setLocked: (pos: number, on: boolean) => void;
}

export const DocumentContext = React.createContext<DocumentContextValue>({ resolved: undefined, missing: [], invalid: [], warnings: [], readOnly: false, chooseAnother: () => {}, canMarkRuns: () => false, markRuns: () => {}, setLocked: () => {} });

const toRef = (id: string | null): Ref | null => {
  const at = id?.indexOf(':') ?? -1;
  return id && at > 0 ? { kind: id.slice(0, at) as RefKind, id: id.slice(at + 1) } : null;
};

/** The fix for each missing reference a publish check placed here: give it back, or pick something else. */
export function FixRows({ blockers }: { blockers: readonly PublishBlocker[] }) {
  const { addBack, chooseAnother, readOnly } = React.useContext(DocumentContext);
  return blockers.map((b) => {
    const ref = toRef(b.id);
    return (
      <div key={`${b.id}/${b.position?.field}/${b.position?.step}`} contentEditable={false} className="flex flex-wrap items-center gap-2 rounded-md border border-destructive px-3 py-2 text-sm" data-testid="missing-fix">
        <span>{b.message}</span>
        {ref && !readOnly && addBack && (
          <Button type="button" variant="outline" size="sm" onClick={() => addBack(ref)}>
            <Plus />
            Add it back
          </Button>
        )}
        {ref && !readOnly && (
          <Button type="button" variant="outline" size="sm" onClick={() => chooseAnother(ref)}>
            <Search />
            Choose another
          </Button>
        )}
      </div>
    );
  });
}

const placed = (missing: readonly PublishBlocker[], field: string, step?: number) =>
  missing.filter((b) => b.kind === 'missing_reference' && b.position?.field === field && (step === undefined || b.position.step === step));

/** A line the publish check noticed and does not block on. The icon and the word say it, not only the colour. */
function WarningLine({ message }: { message: string }) {
  return (
    <p contentEditable={false} className="flex items-start gap-1 text-xs text-warning-text" data-testid="publish-warning">
      <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
      <span>Warning: {message}</span>
    </p>
  );
}

/**
 * A locked heading with the text or the list under it. An optional section with nothing in it is one line, its heading
 * and an Add link, until the person adds to it (or the cursor is in it); read-only, the line says None.
 */
type Chip = { id: string; label: string; icon?: string; text: string };
/** The chip whose sentence is the section's whole text, which draws pressed. */
const chipOn = (chips: Chip[], text: string) => chips.find((c) => c.text.trim() === text.trim())?.id ?? '';

export function BlockView({ node, editor, getPos }: ReactNodeViewProps) {
  const { missing, invalid, warnings, readOnly, removeBlock, pickChip } = React.useContext(DocumentContext);
  const key = node.attrs.key as string;
  const error = invalid.find((i) => i.field === key);
  const errorId = `${React.useId()}-error`;
  const optional = !!node.attrs.optional;
  const empty = node.textContent.trim() === '';
  const [asked, setAsked] = React.useState(false);
  const inside = useEditorState({
    editor,
    selector: (ctx) => {
      const at = getPos();
      const from = ctx.editor.state.selection.from;
      return typeof at === 'number' && from > at && from < at + node.nodeSize;
    },
  });
  const collapsed = optional && empty && !asked && !inside && !error;
  const open = () => {
    setAsked(true);
    requestAnimationFrame(() => {
      const at = getPos();
      if (typeof at !== 'number') return;
      const { state, view } = editor;
      view.dispatch(state.tr.setSelection(Selection.near(state.doc.resolve(at + 1))));
      view.focus();
    });
  };
  const label = node.attrs.label as string;
  return (
    <NodeViewWrapper as="section" role="group" aria-label={label} aria-invalid={error ? true : undefined} aria-describedby={error ? errorId : undefined} data-field={key} data-collapsed={collapsed ? 'yes' : undefined} className="flex flex-col gap-2">
      {/* A plain heading, the size and weight of every other section heading on the page. */}
      <div contentEditable={false} className="flex items-center gap-2 select-none">
        <div role="heading" aria-level={2} className="text-sm font-semibold">
          {label}
          {collapsed && !label.includes('·') && <span className="font-normal text-muted-foreground"> · optional</span>}
        </div>
        {!!node.attrs.note && <span className="text-xs text-muted-foreground">{node.attrs.note as string}</span>}
        {!!node.attrs.removable && !readOnly && removeBlock && (
          <Button type="button" variant="ghost" size="icon" className="ml-auto size-6" aria-label={`Remove ${label}`} title={`Remove ${label}`} onClick={() => removeBlock(key)} data-testid={`brief-remove-${key}`}>
            <X className="size-3.5" />
          </Button>
        )}
        {collapsed && (readOnly ? <span className="text-sm text-muted-foreground">None</span> : (
          <Button type="button" variant="link" size="sm" onClick={open} data-testid={`brief-add-${key}`}>
            <Plus /> Add
          </Button>
        ))}
      </div>
      {!readOnly && pickChip && Array.isArray(node.attrs.chips) && (
        <ToggleGroup type="single" variant="outline" size="sm" value={chipOn(node.attrs.chips as Chip[], node.textContent)} onValueChange={() => {}} contentEditable={false} aria-label={`${label} presets`} className="w-full flex-wrap gap-1 select-none" data-testid={`brief-chips-${key}`}>
          {(node.attrs.chips as Chip[]).map((c) => {
            const Icon = c.icon ? PRESET_ICONS[c.icon] : undefined;
            return (
              <ToggleGroupItem key={c.id} value={c.id} className="min-w-fit flex-none rounded-md border-l" onClick={() => pickChip(key, c.text)} title={c.text}>
                {Icon && <Icon aria-hidden />}
                {c.label}
              </ToggleGroupItem>
            );
          })}
        </ToggleGroup>
      )}
      <NodeViewContent className={cn(collapsed && 'hidden', error && 'rounded-sm ring-2 ring-destructive/40')} />
      {error && (
        <p id={errorId} contentEditable={false} className="text-xs text-destructive-text">
          {error.message}
        </p>
      )}
      {warnings.filter((w) => w.field === key).map((w) => (
        <WarningLine key={w.message} message={w.message} />
      ))}
      <FixRows blockers={placed(missing, key)} />
    </NodeViewWrapper>
  );
}

/** Keeps a step's tool to that step. Read-only, it only says so when on. */
function LockControl({ locked, readOnly, onChange }: { locked: boolean; readOnly: boolean; onChange: (on: boolean) => void }) {
  const label = locked ? 'Only in this step: on' : 'Only in this step';
  if (readOnly) {
    return locked ? (
      <Badge variant="secondary" contentEditable={false} data-testid="step-tool-locked">
        <Lock aria-hidden />
        Only in this step
      </Badge>
    ) : null;
  }
  return (
    <Button type="button" variant="ghost" size="icon" contentEditable={false} className="size-5" aria-label={label} title={label} aria-pressed={locked} data-testid="lock-step-tool" onClick={() => onChange(!locked)}>
      {locked ? <Lock className="size-3" /> : <LockOpen className="size-3" />}
    </Button>
  );
}

/** The step's place among the steps, from 1; 0 while it has no place (as it is being removed). */
function stepNumber(editor: ReactNodeViewProps['editor'], getPos: ReactNodeViewProps['getPos']): number {
  try {
    const at = getPos();
    return at === undefined ? 0 : editor.state.doc.resolve(at).index() + 1;
  } catch {
    return 0;
  }
}

/** One numbered step: what it uses in front, its line, and a check and an if-not line where they were written. */
export function StepView({ node, editor, getPos, updateAttributes }: ReactNodeViewProps) {
  const { missing, invalid, warnings, readOnly, resolved } = React.useContext(DocumentContext);
  const pos = getPos();
  // A step's number is its place among the steps. A step is drawn again only when it changes itself, so the number
  // is read from the editor's state: a step added or removed above changes it and redraws the label and its error.
  const number = useEditorState({ editor, selector: () => stepNumber(editor, getPos) });
  const error = invalid.find((i) => i.field === 'steps' && i.step === number);
  const errorId = `${React.useId()}-error`;
  const use = node.attrs.use as Ref | null;
  // What the step runs is shown once: on the reference in its sentence when it names it there, else as a chip in front.
  const inFront = use && runsIndex(use, refsInNode(node.firstChild)) < 0;
  return (
    <NodeViewWrapper role="group" aria-label={`Step ${number}`} aria-invalid={error ? true : undefined} aria-describedby={error ? errorId : undefined} data-step className="flex gap-2 [counter-increment:step]">
      <span contentEditable={false} aria-hidden className="w-5 shrink-0 text-muted-foreground select-none before:content-[counter(step)_'.']" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {/* The chip floats, so the step's text starts beside it and the check and if-not lines start under it. */}
        <div className="min-w-0">
          {use && inFront && (
            <span contentEditable={false} className="float-left mr-2 inline-flex items-center gap-1">
              <ReferenceBadge reference={use} resolved={resolved} runs />
              {!readOnly && (
                <Button type="button" variant="ghost" size="icon" className="size-5" aria-label="Remove what this step uses" onClick={() => updateAttributes({ use: null, locked: false })}>
                  <X className="size-3" />
                </Button>
              )}
              <LockControl locked={!!node.attrs.locked} readOnly={readOnly} onChange={(on) => updateAttributes({ locked: on })} />
            </span>
          )}
          <NodeViewContent className="min-w-0" />
        </div>
        {error && (
          <p id={errorId} contentEditable={false} className="text-xs text-destructive-text">
            {error.message}
          </p>
        )}
        {warnings.filter((w) => w.field === 'steps' && w.step === number).map((w) => (
          <WarningLine key={w.message} message={w.message} />
        ))}
        <FixRows blockers={placed(missing, 'steps', number)} />
      </div>
    </NodeViewWrapper>
  );
}

// A sentence that states a comparison: a model can pass it on a value that fails it, and a rule cannot.
const COMPARES = /\b(above|below|at least|at most|more than|less than|greater|fewer|exceeds?|equals?|positive|negative|non-?zero|between|no more than|no less than)\b|[<>]/i;

/** A step's check. The save decides whether it is a rule the service runs or a sentence the model judges. */
export function CheckView({ node, updateAttributes }: ReactNodeViewProps) {
  const by = node.attrs.by as 'rule' | 'model' | null;
  // The label describes the text the save classified: an edit clears it, and the next save sets it again.
  const text = node.textContent;
  const before = React.useRef(text);
  React.useEffect(() => {
    if (before.current === text) return;
    before.current = text;
    if (by) updateAttributes({ by: null });
  }, [text, by, updateAttributes]);
  return (
    <NodeViewWrapper data-check className="clear-left ml-1 flex flex-wrap items-baseline gap-x-2 border-l-2 pl-3">
      <span contentEditable={false} className="font-semibold select-none">
        Check:
      </span>
      <NodeViewContent className="min-w-48 flex-1" />
      {by && (
        <span contentEditable={false} className="text-xs text-muted-foreground select-none">
          {by === 'rule' ? 'Checked by a rule' : 'Judged by the model'}
        </span>
      )}
      {by === 'model' && COMPARES.test(text) && (
        <p contentEditable={false} className="basis-full text-xs text-warning-text select-none" data-testid="check-rule-hint">
          This compares a value, and the model may judge it wrong. Write it as a rule the service checks, such as result.balance &gt; 0.
        </p>
      )}
    </NodeViewWrapper>
  );
}

const ACTIONS: Record<IfNot['action'], string> = { retry: 'Try again', goto: 'Go to step', exit: 'End with' };
const DEFAULTS: Record<IfNot['action'], IfNot> = { retry: { action: 'retry', retries: 1 }, goto: { action: 'goto', step: 1 }, exit: { action: 'exit', exit: 'failed' } };

/** What happens when a step's check does not pass: try again, go to a step, or end with an exit. */
export function IfNotView({ node, updateAttributes, deleteNode }: ReactNodeViewProps) {
  const { readOnly } = React.useContext(DocumentContext);
  const value = node.attrs.value as IfNot;
  const set = (next: IfNot) => updateAttributes({ value: next });
  return (
    <NodeViewWrapper data-if-not contentEditable={false} className="clear-left ml-1 flex flex-wrap items-center gap-2 border-l-2 pl-3">
      <span className="font-semibold select-none">If not:</span>
      <Select value={value.action} onValueChange={(a) => set(DEFAULTS[a as IfNot['action']])} disabled={readOnly}>
        <SelectTrigger size="sm" aria-label="If the check does not pass">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(ACTIONS) as IfNot['action'][]).map((a) => (
            <SelectItem key={a} value={a}>
              {ACTIONS[a]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {value.action === 'retry' && (
        <>
          <span className="text-muted-foreground">up to</span>
          <Input type="number" min={0} max={3} className="h-8 w-16" aria-label="Times to try again" disabled={readOnly} value={value.retries ?? 1} onChange={(e) => set({ action: 'retry', retries: Math.max(0, Math.min(3, Number(e.target.value) || 0)) })} />
          <span className="text-muted-foreground">more times</span>
        </>
      )}
      {value.action === 'goto' && <Input type="number" min={1} max={30} className="h-8 w-16" aria-label="Step to go to" disabled={readOnly} value={value.step ?? 1} onChange={(e) => set({ action: 'goto', step: Math.max(1, Math.min(30, Number(e.target.value) || 1)) })} />}
      {value.action === 'exit' && <Input className="h-8 w-40" aria-label="Exit name" placeholder="e.g. failed" disabled={readOnly} value={value.exit ?? ''} onChange={(e) => set({ action: 'exit', exit: e.target.value })} />}
      {!readOnly && (
        <Button type="button" variant="ghost" size="icon" className="size-6" aria-label="Remove the if-not line" onClick={deleteNode}>
          <X className="size-3" />
        </Button>
      )}
    </NodeViewWrapper>
  );
}

/**
 * A reference as a badge with the item's current name, or Missing when the team no longer has it. With `runs` it is the
 * one its step runs, and says so in words as well as to a screen reader.
 */
export function ReferenceBadge({ reference, resolved, runs = false }: { reference: Ref; resolved: readonly ReferenceItem[] | undefined; runs?: boolean }) {
  const chip = chipFor(reference, resolved);
  const Icon = chip.state === 'missing' ? TriangleAlert : KIND_ICON[reference.kind];
  return (
    <Badge
      variant={chip.state === 'missing' ? 'destructive' : reference.kind === 'skill' ? 'secondary' : 'outline'}
      className={chip.state === 'loading' ? 'text-muted-foreground' : undefined}
      role={runs ? 'group' : undefined}
      aria-label={runs ? `This step runs ${chip.label}` : undefined}
      data-testid="reference-chip"
      data-ref={mentionToken(reference)}
      data-state={chip.state}
      data-runs={runs ? '' : undefined}
    >
      <Icon aria-hidden />
      {chip.label}
      {runs && (
        <span className="border-l pl-1.5 text-xs font-medium" data-testid="runs-mark">
          runs
        </span>
      )}
    </Badge>
  );
}

/**
 * A reference in the text. In a step's sentence the builder can make it what the step runs, or stop that; the one that
 * is marked carries the "runs" mark (a decoration from the Runs extension, set when the step's tool is named here).
 */
export function ReferenceView({ node, selected, getPos, decorations }: ReactNodeViewProps) {
  const { resolved, readOnly, canMarkRuns, markRuns, setLocked } = React.useContext(DocumentContext);
  const reference: Ref = { kind: node.attrs.kind, id: node.attrs.id };
  const runs = decorations.some((d) => d.spec?.runs);
  const locked = decorations.some((d) => d.spec?.locked);
  const pos = getPos();
  const canMark = !readOnly && reference.kind !== 'knowledge' && pos !== undefined && canMarkRuns(pos);
  const label = runs ? 'Stop running this' : 'Make this the step’s tool';
  return (
    <NodeViewWrapper as="span" className={`group/ref inline-flex items-center gap-0.5 align-middle ${selected ? 'rounded-md ring-2 ring-ring' : ''}`}>
      <ReferenceBadge reference={reference} resolved={resolved} runs={runs} />
      {canMark && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          contentEditable={false}
          className={`size-5 transition-opacity focus-visible:opacity-100 group-hover/ref:opacity-100 ${selected || runs ? 'opacity-100' : 'opacity-0'}`}
          aria-label={label}
          title={label}
          data-testid={runs ? 'stop-running' : 'make-step-tool'}
          onClick={() => markRuns(getPos()!, runs ? null : reference)}
        >
          {runs ? <Ban className="size-3" /> : <Play className="size-3" />}
        </Button>
      )}
      {runs && pos !== undefined && <LockControl locked={locked} readOnly={readOnly} onChange={(on) => setLocked(getPos()!, on)} />}
    </NodeViewWrapper>
  );
}

export function VariableView({ node, selected }: ReactNodeViewProps) {
  return (
    <NodeViewWrapper as="span" className={selected ? 'rounded-md ring-2 ring-ring' : undefined}>
      <Badge variant="outline" className="font-mono" data-testid="variable-chip">
        <Braces aria-hidden />
        {node.attrs.name}
      </Badge>
    </NodeViewWrapper>
  );
}
