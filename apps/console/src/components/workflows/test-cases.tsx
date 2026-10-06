'use client';

import * as React from 'react';
import { CheckCircle2, FlaskConical, Play, Plus, Trash2, Upload, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import { toastBulk } from '@/components/shared/bulk';
import { DeleteDialog } from '@/components/shared/delete-dialog';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FileUpload, type UploadItem, uploadsBlocker, uploadsReady } from '@/components/shared/file-upload';
import { EmptyState } from '@/components/shared/empty-state';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { useCreateTest, useDeleteTest, useImportTests, useLastValidation, useTests, useValidateWorkflow } from '@/hooks/queries';
import { relativeTime } from '@/lib/format';
import type { TestCaseInput, WorkflowGraph } from '@/lib/types/domain';
import { cn } from '@/lib/utils';

const ANY = '__any';

function AddTestDialog({ open, onOpenChange, tools, onSubmit, isPending }: { open: boolean; onOpenChange: (o: boolean) => void; tools: string[]; onSubmit: (i: TestCaseInput) => Promise<unknown>; isPending: boolean }) {
  const [v, setV] = React.useState<TestCaseInput>({ name: '', input: '', expect: {} });
  const [errors, setErrors] = React.useState<{ name?: string; input?: string; expect?: string }>({});
  React.useEffect(() => {
    if (open) {
      setV({ name: '', input: '', expect: {} });
      setErrors({});
    }
  }, [open]);
  const setExpect = (patch: TestCaseInput['expect']) => setV((s) => ({ ...s, expect: { ...s.expect, ...patch } }));

  const submit = async () => {
    const e = {
      name: v.name.trim() ? undefined : 'Name the case so a failure is recognisable.',
      input: v.input.trim() ? undefined : 'Add the message or event this case sends.',
      expect: v.expect.pauses || v.expect.callsTool || v.expect.replyContains ? undefined : 'Set at least one expectation.',
    };
    setErrors(e);
    if (e.name || e.input || e.expect) return;
    await onSubmit(v);
    onOpenChange(false);
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Add test case"
      description="Runs every time someone validates or requests a publish."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton onClick={submit} isLoading={isPending}>
            Add test case
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <FormField id="tc-name" label="Name" error={errors.name}>
          <Input id="tc-name" aria-invalid={!!errors.name} value={v.name} onChange={(e) => (setV({ ...v, name: e.target.value }), setErrors({ ...errors, name: undefined }))} placeholder="New payee over $50,000" />
        </FormField>
        <FormField id="tc-input" label="Input" error={errors.input} hint="A customer message, or the JSON an event or API call would send.">
          <Textarea id="tc-input" aria-invalid={!!errors.input} value={v.input} onChange={(e) => (setV({ ...v, input: e.target.value }), setErrors({ ...errors, input: undefined }))} className="min-h-24 font-mono text-xs" placeholder='{ "amount": 127800, "payeeAgeHours": 19 }' />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField id="tc-pauses" label="Pauses for review">
            <Select value={v.expect.pauses ?? ANY} onValueChange={(x) => setExpect({ pauses: x === ANY ? undefined : (x as 'yes' | 'no') })}>
              <SelectTrigger id="tc-pauses" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY}>Don&apos;t check</SelectItem>
                <SelectItem value="yes">Must pause</SelectItem>
                <SelectItem value="no">Must not pause</SelectItem>
              </SelectContent>
            </Select>
          </FormField>
          <FormField id="tc-tool" label="Calls tool">
            <Select value={v.expect.callsTool ?? ANY} onValueChange={(x) => setExpect({ callsTool: x === ANY ? undefined : x })}>
              <SelectTrigger id="tc-tool" className="w-full font-mono text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY} className="font-sans">
                  Don&apos;t check
                </SelectItem>
                {tools.map((t) => (
                  <SelectItem key={t} value={t} className="font-mono text-xs">
                    {t}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <FormField id="tc-reply" label="Reply contains" optional error={errors.expect}>
          <Input id="tc-reply" value={v.expect.replyContains ?? ''} onChange={(e) => (setExpect({ replyContains: e.target.value || undefined }), setErrors({ ...errors, expect: undefined }))} placeholder="callback" />
        </FormField>
      </div>
    </DialogShell>
  );
}

/** Parses `name,input,pauses,callsTool,replyContains` with a header row; quoted fields may contain commas. */
function parseCsv(text: string): TestCaseInput[] {
  const rows = text
    .split(/\r?\n/)
    .filter((l) => l.trim())
    .map((line) => (line.match(/("([^"]|"")*"|[^,]*)(,|$)/g) ?? []).map((c) => c.replace(/,$/, '').replace(/^"|"$/g, '').replace(/""/g, '"').trim()));
  return rows.slice(1).map(([name = '', input = '', pauses = '', callsTool = '', replyContains = '']) => ({
    name,
    input,
    expect: { pauses: pauses === 'yes' || pauses === 'no' ? pauses : undefined, callsTool: callsTool || undefined, replyContains: replyContains || undefined },
  }));
}

function ImportDialog({ open, onOpenChange, onImport, isPending }: { open: boolean; onOpenChange: (o: boolean) => void; onImport: (rows: TestCaseInput[], fileId: string) => Promise<unknown>; isPending: boolean }) {
  const [rows, setRows] = React.useState<TestCaseInput[] | null>(null);
  const [upload, setUpload] = React.useState<UploadItem[]>([]);
  const fileId = uploadsReady(upload) ? upload[0].fileId : undefined;
  const waiting = upload.length ? uploadsBlocker(upload) : undefined;
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setRows(null);
      setError(null);
      setUpload([]);
    }
  }, [open]);
  const valid = (rows ?? []).filter((r) => r.name.trim() && r.input.trim());
  const invalid = (rows?.length ?? 0) - valid.length;
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title="Import test cases"
      description="CSV with a header row: name, input, pauses (yes/no), callsTool, replyContains."
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            disabled={!valid.length || !fileId}
            title={waiting}
            onClick={async () => {
              await onImport(rows!, fileId!);
              onOpenChange(false);
            }}
          >
            Import {valid.length || ''}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <FileUpload
          id="tc-file"
          purpose="test_import"
          title="Drop a CSV file here or choose one"
          hint="Rows missing a name or input are skipped and listed after import."
          onChange={setUpload}
          onPick={async ([f]) => {
            setRows(null);
            setError(null);
            try {
              const parsed = parseCsv(await f.text());
              if (!parsed.length) setError('The file has no rows under the header.');
              else setRows(parsed);
            } catch {
              setError('That file could not be read as CSV.');
            }
          }}
          testId="test-import-upload"
        />
        {error && <p className="text-sm text-destructive">{error}</p>}
        {rows && invalid > 0 && <p className="text-sm text-amber-700 dark:text-amber-400">{invalid} row{invalid === 1 ? '' : 's'} without a name or input will be skipped.</p>}
        {rows && (
          <ul className="max-h-48 divide-y overflow-y-auto rounded-md border text-sm">
            {rows.slice(0, 8).map((r, i) => (
              <li key={i} className="truncate px-3 py-1.5">
                {r.name && r.input ? r.name : <span className="text-destructive">{r.name || 'Unnamed row'} · skipped</span>}
              </li>
            ))}
            {rows.length > 8 && <li className="px-3 py-1.5 text-muted-foreground">and {rows.length - 8} more</li>}
          </ul>
        )}
      </div>
    </DialogShell>
  );
}

const expectChips = (e: TestCaseInput['expect']) =>
  [e.pauses === 'yes' && 'Pauses', e.pauses === 'no' && 'No pause', e.callsTool && `Calls ${e.callsTool}`, e.replyContains && `Says “${e.replyContains}”`].filter(Boolean) as string[];

/** Test cases for one workflow and their latest results. Runs here test the live version. */
export function TestCases({ workflowId, liveGraph, tools }: { workflowId: string; liveGraph: WorkflowGraph; tools: string[] }) {
  const query = useTests(workflowId);
  const last = useLastValidation(workflowId);
  const validate = useValidateWorkflow(workflowId);
  const create = useCreateTest(workflowId);
  const importRows = useImportTests(workflowId);
  const remove = useDeleteTest();
  const [addOpen, setAddOpen] = React.useState(false);
  const [importOpen, setImportOpen] = React.useState(false);
  const [deleting, setDeleting] = React.useState<{ id: string; name: string } | null>(null);
  const results = new Map((last.data?.results ?? []).map((r) => [r.caseId, r]));

  if (query.isPending)
    return (
      <div className="flex flex-col gap-2">
        <div className="mb-2 flex items-center justify-between">
          <Skeleton className="h-5 w-64" />
          <Skeleton className="h-8 w-80" />
        </div>
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  if (query.isError) return <QueryError what="test cases" onRetry={() => query.refetch()} retrying={query.isFetching} />;

  const s = last.data?.summary;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-sm">
          {s ? (
            <>
              Last run {relativeTime(last.data!.ranAt)} on the {last.data!.target} version: <span className="font-semibold tabular-nums">{s.passed}</span>/{s.total} passed
              {s.regressions > 0 && <span className="text-red-600 dark:text-red-400"> · {s.regressions} regressions</span>}
            </>
          ) : (
            <span className="text-muted-foreground">Not run yet.</span>
          )}
        </div>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}>
            <Upload className="size-3.5" /> Import CSV
          </Button>
          <Button variant="outline" size="sm" onClick={() => setAddOpen(true)}>
            <Plus className="size-3.5" /> Add test case
          </Button>
          <LoadingButton
            size="sm"
            isLoading={validate.isPending}
            disabled={!query.data.length}
            loadingText="Running…"
            onClick={() =>
              validate.mutate({ graph: liveGraph, target: 'live' }, {
                onSuccess: (r) => toast.success(`${r.summary.passed} of ${r.summary.total} passed on the live version`),
                onError: (e) => toast.error('Tests could not run', { description: e.message }),
              })
            }
          >
            <Play className="size-3.5" /> Run tests
          </LoadingButton>
        </div>
      </div>

      {query.data.length === 0 ? (
        <EmptyState
          icon={FlaskConical}
          title="No test cases"
          description="Add the cases that must keep working. They run when someone requests a publish, and the approver sees the results."
          action={{ label: 'Add test case', onClick: () => setAddOpen(true) }}
          secondaryAction={{ label: 'Import CSV', onClick: () => setImportOpen(true) }}
        />
      ) : (
        <div className="overflow-hidden rounded-md border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Case</TableHead>
                <TableHead>Expects</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Last result</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {query.data.map((t) => {
                const r = results.get(t.id);
                return (
                  <TableRow key={t.id}>
                    <TableCell className="max-w-80">
                      <div className="font-medium">{t.name}</div>
                      <div className="truncate font-mono text-xs text-muted-foreground">{t.input}</div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {expectChips(t.expect).map((c) => (
                          <Badge key={c} variant="secondary" className="font-normal">
                            {c}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">{t.source === 'run' ? 'From a run' : t.source === 'csv' ? 'CSV' : 'Manual'}</TableCell>
                    <TableCell>
                      {r ? (
                        <span className={cn('inline-flex items-center gap-1.5 text-xs', r.draft.passed ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-600 dark:text-red-400')}>
                          {r.draft.passed ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
                          {r.draft.passed ? 'Passed' : r.draft.failure}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">Not run</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-8"
                        aria-label={`Delete ${t.name}`}
                        onClick={() => setDeleting({ id: t.id, name: t.name })}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <AddTestDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        tools={tools}
        isPending={create.isPending}
        onSubmit={async (i) => {
          await create.mutateAsync(i);
          toast.success(`Added ${i.name}`);
        }}
      />
      <DeleteDialog
        open={!!deleting}
        onOpenChange={(o) => !o && setDeleting(null)}
        entityType="test case"
        entityName={deleting?.name}
        description={`“${deleting?.name}” stops running on publish requests.`}
        isLoading={remove.isPending}
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await remove.mutateAsync(deleting.id);
            toast.success(`Deleted ${deleting.name}`);
            setDeleting(null);
          } catch (e) {
            toast.error('Couldn’t delete the test case', { description: (e as Error).message });
          }
        }}
      />
      <ImportDialog
        open={importOpen}
        onOpenChange={setImportOpen}
        isPending={importRows.isPending}
        onImport={async (rows, fileId) => {
          const res = await importRows.mutateAsync({ rows, fileId });
          toastBulk(res, 'Imported', 'test case', (id) => `Row ${Number(id) + 2}`);
        }}
      />
    </div>
  );
}
