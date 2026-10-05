'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal, Pencil, Plus, Tags, Trash2 } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { FormField, StopRowClick } from '@/components/shared/form-field';
import { TagInput } from '@/components/shared/tag-input';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useSticky } from '@/hooks/use-sticky';
import type { EmailWorkflowConfig, Intent, IntentField } from '@/lib/types/cases';

import { actionLabel } from './action-label';
import { ConfigNote } from './config-note';

type Row = Intent & { onRowClick: (i: Intent) => void; rowTestId: string };

const snake = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

/** Intents tab of an email intake workflow: what the classifier recognises, what it extracts, and what it drafts. */
export function IntentsTab({ config, onChange, actionOptions }: { config: EmailWorkflowConfig; onChange: (c: EmailWorkflowConfig) => void; actionOptions: string[] }) {
  const [editing, setEditing] = React.useState<Intent | 'new' | null>(null);
  const [deleting, setDeleting] = React.useState<Intent | null>(null);
  const shownDelete = useSticky(deleting);

  const save = (intent: Intent, previousId?: string) => {
    const exists = config.intents.some((i) => i.id === previousId);
    const intents = exists ? config.intents.map((i) => (i.id === previousId ? intent : i)) : [...config.intents, intent];
    // A new intent gets a route to the fallback queue, so mail classified into it never lands nowhere.
    const routes = exists
      ? config.routes.map((r) => (r.intentId === previousId ? { ...r, intentId: intent.id } : r))
      : [...config.routes, { intentId: intent.id, queue: config.fallbackQueue, priority: 'normal' as const, slaHours: 24, businessHours: true }];
    onChange({ ...config, intents, routes });
  };

  const columns: ColumnDef<Row>[] = [
    {
      id: 'name',
      accessorFn: (r) => `${r.name} ${r.description}`,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Intent" />,
      cell: ({ row }) => (
        <div className="min-w-56">
          <div className="font-medium">{row.original.name}</div>
          <div className="line-clamp-1 text-xs text-muted-foreground">{row.original.description}</div>
        </div>
      ),
      enableHiding: false,
    },
    {
      id: 'examples',
      accessorFn: (r) => r.examples.length,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Examples" />,
      cell: ({ row }) => <span className={row.original.examples.length < 2 ? 'text-xs font-medium text-amber-700 dark:text-amber-400' : 'text-muted-foreground tabular-nums'}>{row.original.examples.length < 2 ? `${row.original.examples.length} · add more` : row.original.examples.length}</span>,
    },
    {
      id: 'fields',
      accessorFn: (r) => r.fields.map((f) => f.label).join(', '),
      header: ({ column }) => <DataTableColumnHeader column={column} title="Extracts" />,
      cell: ({ getValue }) => <span className="line-clamp-1 max-w-64 text-xs text-muted-foreground">{(getValue() as string) || '—'}</span>,
      enableSorting: false,
    },
    {
      id: 'actions_drafted',
      accessorFn: (r) => r.actions.map(actionLabel).join(', '),
      header: ({ column }) => <DataTableColumnHeader column={column} title="Drafts" />,
      cell: ({ getValue }) => <span className="line-clamp-1 max-w-64 text-xs text-muted-foreground">{(getValue() as string) || '—'}</span>,
      enableSorting: false,
    },
    {
      id: 'menu',
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => (
        <StopRowClick>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="size-8" aria-label={`Actions for ${row.original.name}`}>
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setEditing(row.original)}>
                <Pencil className="size-4" /> Edit
              </DropdownMenuItem>
              <DropdownMenuItem className="text-destructive" onClick={() => setDeleting(row.original)}>
                <Trash2 className="size-4" /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </StopRowClick>
      ),
      enableSorting: false,
      enableHiding: false,
      meta: { className: 'w-12' },
    },
  ];

  const rows: Row[] = config.intents.map((i) => ({ ...i, onRowClick: (x: Intent) => setEditing(x), rowTestId: `intent-row-${i.id}` }));

  return (
    <div className="flex flex-col gap-4" data-testid="intents-tab">
      <ConfigNote>
        The agent sorts each email into one of these intents. Emails below {Math.round(config.confidenceThreshold * 100)}% confidence go to {config.fallbackQueue} for a person to sort.
      </ConfigNote>
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        searchColumn="name"
        searchPlaceholder="Search intents…"
        hideViewSwitcher
        toolbarExtra={
          <Button size="sm" onClick={() => setEditing('new')}>
            <Plus className="size-4" /> Add intent
          </Button>
        }
        emptyState={<EmptyState icon={Tags} title="No intents yet" description="Add the kinds of request this mailbox receives, each with two or three example emails." action={{ label: 'Add intent', onClick: () => setEditing('new') }} />}
      />

      <IntentDialog
        open={!!editing}
        onOpenChange={(o) => !o && setEditing(null)}
        intent={editing === 'new' ? null : editing}
        takenIds={config.intents.map((i) => i.id)}
        actionOptions={actionOptions}
        onSave={(intent, previousId) => {
          save(intent, previousId);
          setEditing(null);
        }}
      />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="intent"
        entityName={shownDelete?.name ?? ''}
        description="Its routing rule goes with it. Open cases keep their intent; new mail like this goes to the fallback queue."
        onConfirm={() => {
          if (!deleting) return;
          onChange({ ...config, intents: config.intents.filter((i) => i.id !== deleting.id), routes: config.routes.filter((r) => r.intentId !== deleting.id) });
          setDeleting(null);
        }}
      />
    </div>
  );
}

function IntentDialog({
  open,
  onOpenChange,
  intent,
  takenIds,
  actionOptions,
  onSave,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  intent: Intent | null;
  takenIds: string[];
  actionOptions: string[];
  onSave: (intent: Intent, previousId?: string) => void;
}) {
  const shown = useSticky(open ? { intent } : null);
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [examples, setExamples] = React.useState('');
  const [fields, setFields] = React.useState<IntentField[]>([]);
  const [actions, setActions] = React.useState<string[]>([]);
  const [errors, setErrors] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    if (!open) return;
    setName(intent?.name ?? '');
    setDescription(intent?.description ?? '');
    setExamples(intent?.examples.join('\n\n') ?? '');
    setFields(intent?.fields ?? []);
    setActions(intent?.actions ?? ['send_reply']);
    setErrors({});
  }, [open, intent]);

  const submit = () => {
    const ex = examples.split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean);
    const id = intent?.id ?? snake(name);
    const e: Record<string, string> = {};
    if (!name.trim()) e.name = 'Name the intent.';
    else if (!intent && takenIds.includes(id)) e.name = 'An intent with this name already exists.';
    if (ex.length < 2) e.examples = 'Give at least two example emails, separated by a blank line.';
    if (!actions.length) e.actions = 'Choose at least one action, even if it is only a reply.';
    setErrors(e);
    if (Object.keys(e).length) return;
    onSave({ id, name: name.trim(), description: description.trim(), examples: ex.slice(0, 5), fields, actions }, intent?.id);
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={shown?.intent ? `Edit ${shown.intent.name}` : 'Add intent'}
      description="Changes go into the draft. They reach live mail only after the workflow is published."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit}>{shown?.intent ? 'Save intent' : 'Add intent'}</Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="intent-name" label="Name" error={errors.name}>
          <Input id="intent-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Dispute a card charge" aria-invalid={!!errors.name} />
        </FormField>
        <FormField id="intent-description" label="Description" optional hint="One sentence the classifier reads alongside the examples.">
          <Input id="intent-description" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Customer does not recognise a card transaction" />
        </FormField>
        <FormField id="intent-examples" label="Example emails" error={errors.examples} hint="Two to five, separated by a blank line. Real wording beats tidy wording.">
          <Textarea id="intent-examples" rows={7} value={examples} onChange={(e) => setExamples(e.target.value)} placeholder="e.g. There is a charge of $412 on my card ending 4471 that I did not make." aria-invalid={!!errors.examples} />
        </FormField>
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Fields to extract</span>
            <Button variant="ghost" size="sm" onClick={() => setFields((f) => [...f, { key: '', label: '', required: false }])}>
              <Plus className="size-4" /> Add field
            </Button>
          </div>
          {fields.length === 0 && <p className="text-xs text-muted-foreground">No fields. The case opens with the email only.</p>}
          {fields.map((f, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <Input
                aria-label={`Field ${i + 1} label`}
                className="min-w-40 flex-1"
                value={f.label}
                placeholder="e.g. Card (last 4)"
                onChange={(e) => setFields((all) => all.map((x, j) => (j === i ? { ...x, label: e.target.value, key: snake(e.target.value) } : x)))}
              />
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <Switch checked={f.required} onCheckedChange={(v) => setFields((all) => all.map((x, j) => (j === i ? { ...x, required: v } : x)))} aria-label={`Field ${i + 1} required`} />
                Required
              </label>
              <Button variant="ghost" size="icon" className="size-8" aria-label={`Remove field ${i + 1}`} onClick={() => setFields((all) => all.filter((_, j) => j !== i))}>
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </div>
        <FormField id="intent-actions" label="Actions the agent drafts" error={errors.actions} hint="Each runs only as its approval rule allows.">
          <TagInput id="intent-actions" value={actions} onChange={setActions} suggestions={actionOptions} format={actionLabel} placeholder="e.g. Reply to customer" />
        </FormField>
      </div>
    </DialogShell>
  );
}
