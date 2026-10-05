'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { MoreHorizontal, Pencil, Plus, ShieldCheck, Trash2 } from 'lucide-react';

import { DataTableColumnHeader } from '@/components/data-table-column-header';
import { DataTableWithViews } from '@/components/data-table-with-views';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { EmptyState } from '@/components/shared/empty-state';
import { FormField, StopRowClick } from '@/components/shared/form-field';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useSticky } from '@/hooks/use-sticky';
import type { ApprovalRule, EmailWorkflowConfig } from '@/lib/types/cases';

import { actionLabel } from './action-label';
import { ConfigNote } from './config-note';

type Row = ApprovalRule & { onRowClick: (r: ApprovalRule) => void; rowTestId: string };

/** Approval rules tab: who signs off on each action the agent drafts, and when two people must. */
export function ApprovalsTab({
  config,
  onChange,
  actionOptions,
  moneyTools,
  approverGroups,
}: {
  config: EmailWorkflowConfig;
  onChange: (c: EmailWorkflowConfig) => void;
  actionOptions: string[];
  moneyTools: string[];
  approverGroups: string[];
}) {
  const [editing, setEditing] = React.useState<ApprovalRule | 'new' | null>(null);
  const [deleting, setDeleting] = React.useState<ApprovalRule | null>(null);
  const shownDelete = useSticky(deleting);

  // Actions an intent drafts with no rule run without anyone signing off; the table calls them out.
  const drafted = [...new Set(config.intents.flatMap((i) => i.actions))];
  const ungoverned = drafted.filter((a) => !config.approvals.some((r) => r.action === a));

  const columns: ColumnDef<Row>[] = [
    {
      id: 'label',
      accessorFn: (r) => r.label,
      header: ({ column }) => <DataTableColumnHeader column={column} title="Action" />,
      cell: ({ row }) => (
        <div className="min-w-48">
          <div className="font-medium">{row.original.label}</div>
          <div className="font-mono text-xs text-muted-foreground">{row.original.action}</div>
        </div>
      ),
      enableHiding: false,
    },
    {
      accessorKey: 'approverGroup',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Approved by" />,
      cell: ({ row }) => <span className="whitespace-nowrap text-muted-foreground">{row.original.approverGroup}</span>,
    },
    {
      accessorKey: 'fourEyes',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Two approvers" />,
      cell: ({ row }) => <span className="text-xs text-muted-foreground">{row.original.fourEyes ? 'Yes' : 'No'}</span>,
    },
    {
      accessorKey: 'autoApproveBelow',
      header: ({ column }) => <DataTableColumnHeader column={column} title="Runs without sign-off" />,
      cell: ({ row }) => <span className="text-xs whitespace-nowrap text-muted-foreground tabular-nums">{row.original.autoApproveBelow == null ? 'Never' : `Under $${row.original.autoApproveBelow}`}</span>,
    },
    {
      id: 'menu',
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => (
        <StopRowClick align="start">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="size-8" aria-label={`Actions for ${row.original.label}`}>
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
  const rows: Row[] = config.approvals.map((r) => ({ ...r, onRowClick: (x: ApprovalRule) => setEditing(x), rowTestId: `approval-row-${r.id}` }));

  return (
    <div className="flex flex-col gap-4" data-testid="approvals-tab">
      <ConfigNote>Every drafted action waits on a case until it is approved here, one action at a time. Money movement needs two people.</ConfigNote>
      {ungoverned.length > 0 && (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-900 dark:text-amber-200" role="status">
          No rule for {ungoverned.map((a) => `“${actionLabel(a)}”`).join(', ')}. {ungoverned.length === 1 ? 'It runs' : 'They run'} as soon as the agent drafts {ungoverned.length === 1 ? 'it' : 'them'}.
        </p>
      )}
      <DataTableWithViews
        columns={columns}
        data={rows}
        getRowId={(r) => r.id}
        hideViewSwitcher
        toolbarExtra={
          <Button size="sm" onClick={() => setEditing('new')}>
            <Plus className="size-4" /> Add rule
          </Button>
        }
        emptyState={<EmptyState icon={ShieldCheck} title="No approval rules" description="Without rules every drafted action runs on its own." action={{ label: 'Add rule', onClick: () => setEditing('new') }} />}
      />

      <RuleDialog
        open={!!editing}
        onOpenChange={(o) => !o && setEditing(null)}
        rule={editing === 'new' ? null : editing}
        actionOptions={actionOptions.filter((a) => (editing && editing !== 'new' ? a === editing.action : true) || !config.approvals.some((r) => r.action === a))}
        moneyTools={moneyTools}
        approverGroups={approverGroups}
        onSave={(rule) => {
          const exists = config.approvals.some((r) => r.id === rule.id);
          onChange({ ...config, approvals: exists ? config.approvals.map((r) => (r.id === rule.id ? rule : r)) : [...config.approvals, rule] });
          setEditing(null);
        }}
      />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="approval rule"
        entityName={shownDelete?.label ?? ''}
        description="Once published, this action runs without sign-off on new cases."
        onConfirm={() => {
          if (!deleting) return;
          onChange({ ...config, approvals: config.approvals.filter((r) => r.id !== deleting.id) });
          setDeleting(null);
        }}
      />
    </div>
  );
}

function RuleDialog({
  open,
  onOpenChange,
  rule,
  actionOptions,
  moneyTools,
  approverGroups,
  onSave,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  rule: ApprovalRule | null;
  actionOptions: string[];
  moneyTools: string[];
  approverGroups: string[];
  onSave: (r: ApprovalRule) => void;
}) {
  const shown = useSticky(open ? { rule } : null);
  const [action, setAction] = React.useState('');
  const [group, setGroup] = React.useState('');
  const [fourEyes, setFourEyes] = React.useState(false);
  const [limit, setLimit] = React.useState('');
  const [errors, setErrors] = React.useState<Record<string, string>>({});

  React.useEffect(() => {
    if (!open) return;
    setAction(rule?.action ?? '');
    setGroup(rule?.approverGroup ?? '');
    setFourEyes(rule?.fourEyes ?? false);
    setLimit(rule?.autoApproveBelow == null ? '' : String(rule.autoApproveBelow));
    setErrors({});
  }, [open, rule]);

  const moves = moneyTools.includes(action);
  const submit = () => {
    const e: Record<string, string> = {};
    if (!action) e.action = 'Choose the action this rule governs.';
    if (!group) e.group = 'Choose who approves it.';
    if (limit && !(Number(limit) > 0)) e.limit = 'Enter an amount above zero, or leave it empty.';
    if (moves && !fourEyes) e.fourEyes = 'Actions that move money need two approvers.';
    setErrors(e);
    if (Object.keys(e).length) return;
    onSave({
      id: rule?.id ?? `ap_${action}`,
      action,
      label: rule?.label ?? actionLabel(action).replace(/^\w/, (c) => c.toUpperCase()),
      kind: action === 'send_reply' ? 'reply' : 'tool',
      approverGroup: group,
      fourEyes,
      autoApproveBelow: limit ? Number(limit) : null,
    });
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={shown?.rule ? `Edit ${shown.rule.label}` : 'Add approval rule'}
      description="Applies to new cases after the workflow is published."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit}>{shown?.rule ? 'Save rule' : 'Add rule'}</Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="rule-action" label="Action" error={errors.action}>
          <Select value={action} onValueChange={setAction} disabled={!!rule}>
            <SelectTrigger id="rule-action" className="w-full" aria-invalid={!!errors.action}>
              <SelectValue placeholder="Choose an action" />
            </SelectTrigger>
            <SelectContent>
              {actionOptions.map((a) => (
                <SelectItem key={a} value={a}>
                  {actionLabel(a)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="rule-group" label="Approved by" error={errors.group}>
          <Select value={group} onValueChange={setGroup}>
            <SelectTrigger id="rule-group" className="w-full" aria-invalid={!!errors.group}>
              <SelectValue placeholder="Choose a group" />
            </SelectTrigger>
            <SelectContent>
              {approverGroups.map((g) => (
                <SelectItem key={g} value={g}>
                  {g}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField id="rule-four-eyes" label="Two approvers" error={errors.fourEyes} hint={moves ? 'Required: this tool moves money.' : 'A second person from the group must also approve.'}>
          <Switch id="rule-four-eyes" checked={fourEyes} onCheckedChange={setFourEyes} />
        </FormField>
        <FormField id="rule-limit" label="Run without sign-off under" optional error={errors.limit} hint="Leave empty to always ask. Applies to actions with an amount.">
          <Input id="rule-limit" type="number" min={0} value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="e.g. 50" />
        </FormField>
      </div>
    </DialogShell>
  );
}
