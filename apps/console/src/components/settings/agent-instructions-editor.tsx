'use client';

import * as React from 'react';
import { ChevronDown, ChevronUp, Info, Plus, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { PageSkeleton } from '@/components/shared/page-skeleton';
import { QueryError } from '@/components/shared/query-states';
import { SchemaForm, formFromSchema, type Schema } from '@/components/shared/schema-form';
import { SettingsPageLayout } from '@/components/settings/settings-page-layout';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { useInstructionSections, useResetInstructionSections, useSaveInstructionSections } from '@/hooks/instruction-sections';
import { useCan } from '@/hooks/me-queries';
import { inOrder } from '@/lib/brief-sections';
import type { InstructionSection, InstructionSectionList, PresetIcon } from '@/lib/types/domain';

const LABEL_MAX = 40;
const ICONS: PresetIcon[] = ['smile', 'sun', 'scale', 'briefcase', 'zap', 'message', 'heart', 'shield', 'star', 'book'];

/** The fields of one list entry the page edits; a menu section also has a group and can be hidden. */
const itemSchema = (kind: InstructionSection['kind']): Schema => ({
  type: 'object',
  properties: {
    label: { type: 'string', title: 'Label', description: 'The heading the prompt writes this section under.' },
    hint: { type: 'string', title: 'Hint', format: 'textarea', description: 'What the section is for, shown to builders.' },
    example: { type: 'string', title: 'Example line', description: 'One line shown beside the section in Add section and in the empty section.' },
    ...(kind === 'menu'
      ? {
          group: { type: 'string', title: 'Menu group', description: 'The heading it is listed under in Add section. Empty lists it under Your sections.' },
          hidden: { type: 'boolean', title: 'Hidden from Add section', description: 'Agents that already hold it keep it and its text.' },
        }
      : {}),
    presets: {
      type: 'array',
      title: 'Presets',
      description: 'Sentences offered as chips above the section. Picking one writes it as text the builder can edit.',
      items: {
        type: 'object',
        properties: {
          label: { type: 'string', title: 'Label' },
          icon: { type: 'string', title: 'Icon', oneOf: ICONS.map((i) => ({ const: i, title: i.charAt(0).toUpperCase() + i.slice(1) })) },
          text: { type: 'string', title: 'Sentence', format: 'textarea' },
        },
        required: ['label', 'text'],
      },
    },
  },
  required: ['label'],
});

const LIMIT_SCHEMA: Schema = { type: 'object', properties: { customMax: { type: 'integer', title: 'Sections of their own per agent', description: 'How many sections of their own a builder may add to one agent.', default: 5 } } };
const LIMIT_FORM = formFromSchema(LIMIT_SCHEMA);
const KIND_WORD: Record<InstructionSection['kind'], string> = { fixed: 'Part of every brief', menu: 'Menu section', custom: 'Builder’s own' };

const folded = (s: string) => s.split(/\s+/).filter(Boolean).join(' ').toLowerCase();
const renumbered = (items: InstructionSection[]) => items.map((s, order) => ({ ...s, order }));

/**
 * Settings > Agent instructions: the workspace's list of sections an agent's brief may hold (agents-service
 * `/v1/agent-instruction-sections`). An admin renames, reorders, hides and adds sections and edits their hints, example
 * lines and presets, then saves; a reader sees the list with no control to change it. The fields of each entry are the
 * shared schema form over `itemSchema`.
 */
export function AgentInstructionsEditor() {
  // The service lets a team's Admin change the list (settings.manage in the team the request acts in), but the grid
  // /v1/me serves holds settings.manage only in the Security team. Until the grid has a cell for this list, access.manage,
  // which a team's Admin holds, stands in; a person the service refuses sees its message when saving.
  const manages = useCan('settings', 'manage');
  const admin = useCan('access', 'manage');
  const may = manages === true || admin === true;
  const query = useInstructionSections();
  const save = useSaveInstructionSections();
  const reset = useResetInstructionSections();
  const [edit, setEdit] = React.useState<InstructionSectionList | null>(null);
  const [naming, setNaming] = React.useState(false);
  const [name, setName] = React.useState('');
  const [nameError, setNameError] = React.useState<string | null>(null);
  const [asking, setAsking] = React.useState(false);
  const [problem, setProblem] = React.useState<string | null>(null);
  const nameId = React.useId();
  const list = edit ?? query.data;
  const items = React.useMemo(() => (list ? inOrder(list.sections) : []), [list]);
  const blank = items.some((s) => !s.label.trim());

  const change = (next: InstructionSection[], customMax = list?.customMax ?? 5) => {
    setProblem(null);
    setEdit({ sections: renumbered(next), customMax });
  };
  const move = (at: number, by: -1 | 1) => {
    const next = [...items];
    [next[at], next[at + by]] = [next[at + by], next[at]];
    change(next);
  };
  const addNamed = () => {
    const label = name.trim();
    if (!label) return setNameError('Give the section a name.');
    if (label.length > LABEL_MAX) return setNameError(`A section's name is at most ${LABEL_MAX} characters.`);
    if (items.some((s) => folded(s.label) === folded(label))) return setNameError(`${label} is already a section. Give each its own name.`);
    change([...items, { id: '', label, hint: '', kind: 'menu', order: items.length, required: false, hidden: false, drives: 'eval-tag', group: '', example: '', presets: [] }]);
    setNaming(false);
    setName('');
    setNameError(null);
  };
  const saveNow = () =>
    list &&
    save.mutate(list, {
      onSuccess: () => {
        setEdit(null);
        toast.success('Agent instructions saved');
      },
      onError: (e) => setProblem(e instanceof Error ? e.message : 'The list was not saved.'),
    });

  return (
    <SettingsPageLayout
      section="Agent instructions"
      sample={false}
      description="The sections an agent’s brief may hold, their order in the prompt, and the example lines and presets builders see when they add one."
      actions={
        may && list ? (
          <>
            <Button variant="outline" aria-label="Reset to default" title="Reset to default" onClick={() => setAsking(true)} data-testid="instruction-sections-reset">
              <RotateCcw className="size-4" /> Reset
            </Button>
            <LoadingButton onClick={saveNow} disabled={edit === null || blank} isLoading={save.isPending} loadingText="Saving…" data-testid="instruction-sections-save">
              Save
            </LoadingButton>
          </>
        ) : undefined
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : query.isError || !list ? (
        <QueryError what="the agent instruction sections" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} testId="instruction-sections-error" />
      ) : (
        <div className="flex min-w-0 flex-col gap-4" data-testid="instruction-sections">
          {!may && (
            <Alert>
              <Info />
              <AlertDescription>You can read this list. Changing it needs the settings manage right.</AlertDescription>
            </Alert>
          )}
          {problem && (
            <Alert variant="destructive" role="alert" data-testid="instruction-sections-problem">
              <AlertDescription>{problem}</AlertDescription>
            </Alert>
          )}
          {blank && <p className="text-sm text-destructive-text">Every section needs a label before the list can be saved.</p>}
          <div className="max-w-sm">
            <SchemaForm schema={LIMIT_SCHEMA} form={LIMIT_FORM} value={{ customMax: list.customMax }} idPrefix="instruction-limit" readOnly={!may} onChange={(v) => change(items, typeof v.customMax === 'number' ? v.customMax : 5)} />
          </div>
          <ol className="flex flex-col gap-2" aria-label="Sections in the order the prompt writes them">
            {items.map((item, i) => (
              <li key={`${item.id || 'new'}-${i}`} className="rounded-lg border bg-card">
                <Collapsible>
                  <div className="flex flex-wrap items-center gap-2 px-3 py-2">
                    <CollapsibleTrigger asChild>
                      <Button type="button" variant="ghost" size="sm" className="min-w-0 flex-1 justify-start gap-2 text-left" aria-label={`${item.label || 'Unnamed section'}, details`}>
                        <ChevronDown className="size-4 shrink-0" aria-hidden />
                        <span className="truncate text-sm font-medium">{item.label}</span>
                      </Button>
                    </CollapsibleTrigger>
                    <Badge variant="outline" className="max-sm:hidden">{KIND_WORD[item.kind]}</Badge>
                    {item.hidden && <Badge variant="secondary">Hidden</Badge>}
                    {may && (
                      <span className="flex items-center gap-0.5">
                        <Button type="button" variant="ghost" size="icon" disabled={i === 0} aria-label={`Move ${item.label} up`} onClick={() => move(i, -1)}>
                          <ChevronUp className="size-4" />
                        </Button>
                        <Button type="button" variant="ghost" size="icon" disabled={i === items.length - 1} aria-label={`Move ${item.label} down`} onClick={() => move(i, 1)}>
                          <ChevronDown className="size-4" />
                        </Button>
                        {item.kind === 'menu' && (
                          <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${item.label}`} onClick={() => change(items.filter((_, j) => j !== i))}>
                            <Trash2 className="size-4" />
                          </Button>
                        )}
                      </span>
                    )}
                  </div>
                  <CollapsibleContent className="border-t px-3 py-3">
                    <SchemaForm
                      schema={itemSchema(item.kind)}
                      value={{ label: item.label, hint: item.hint, example: item.example, group: item.group, hidden: item.hidden, presets: item.presets }}
                      idPrefix={`instruction-${item.id || `new${i}`}`}
                      readOnly={!may}
                      onChange={(next) => change(items.map((s, j) => (j === i ? { ...s, label: String(next.label ?? ''), hint: String(next.hint ?? ''), example: String(next.example ?? ''), group: String(next.group ?? ''), hidden: next.hidden === true, presets: (Array.isArray(next.presets) ? next.presets : []) as InstructionSection['presets'] } : s)))}
                      form={formFromSchema(itemSchema(item.kind))}
                    />
                  </CollapsibleContent>
                </Collapsible>
              </li>
            ))}
          </ol>
          {may && (
            <div className="flex flex-col gap-2">
              <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => setNaming(true)}>
                <Plus className="size-4" /> Add section
              </Button>
              {naming && (
                <div className="flex flex-wrap items-start gap-2">
                  <FormField id={nameId} label="Section name" error={nameError ?? undefined} className="min-w-0 flex-1 basis-56">
                    <Input
                      id={nameId}
                      value={name}
                      autoFocus
                      placeholder="e.g. Compliance notes"
                      aria-invalid={nameError ? true : undefined}
                      onChange={(e) => {
                        setName(e.target.value);
                        setNameError(null);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          addNamed();
                        } else if (e.key === 'Escape') {
                          setNaming(false);
                          setName('');
                          setNameError(null);
                        }
                      }}
                    />
                  </FormField>
                  <div className="flex gap-2 pt-6">
                    <Button type="button" size="sm" onClick={addNamed}>
                      Add
                    </Button>
                    <Button type="button" variant="ghost" size="sm" onClick={() => { setNaming(false); setName(''); setNameError(null); }}>
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Put the default list back?</AlertDialogTitle>
            <AlertDialogDescription>Your labels, order, example lines, presets and added sections are replaced by the default list. Agents already saved keep the prompt they have.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                reset.mutate(undefined, {
                  onSuccess: () => {
                    setEdit(null);
                    toast.success('Default list restored');
                  },
                  onError: (e) => toast.error(e instanceof Error ? e.message : 'The list was not reset.'),
                })
              }
            >
              Reset list
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SettingsPageLayout>
  );
}
