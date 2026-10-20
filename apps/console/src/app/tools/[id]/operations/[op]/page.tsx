'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import { SearchX, ShieldCheck, Wrench } from 'lucide-react';
import { toast } from 'sonner';

import { PageLayout } from '@/components/page-layout';
import { BuilderOnly } from '@/components/shared/builder-only';
import { EmptyState } from '@/components/shared/empty-state';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { OperationSheet } from '@/components/tools/operation-sheet';
import { draftOf, patchOf, ToolWorkbench, type WorkbenchDraft } from '@/components/tools/tool-workbench';
import { Button } from '@/components/ui/button';
import { useTestModule, useToolModule, useUpdateOperation } from '@/hooks/tool-module-queries';
import { ApiError } from '@/lib/api/contract';
import type { OperationPatch } from '@/lib/types/tool-modules';

/** One tool operation on its own page (c-088): edit its call, inputs, mock and transform, and try them before staging. */
export default function OperationWorkbenchPage() {
  const params = useParams<{ id: string; op: string }>();
  const name = decodeURIComponent(params.op);
  const mod = useToolModule(params.id);
  const test = useTestModule();
  const update = useUpdateOperation();
  const [policyOpen, setPolicyOpen] = React.useState(false);
  const [inputErrors, setInputErrors] = React.useState<Record<string, string>>({});
  const m = mod.data;
  const op = m?.operations.find((o) => o.name === name);
  const [draft, setDraft] = React.useState<WorkbenchDraft | null>(null);
  // A fresh definition after staging (or another tab's edit) replaces the draft; typing in between is kept.
  const loaded = op && m ? JSON.stringify(draftOf(op, m.endpoint)) : '';
  React.useEffect(() => {
    if (op && m) setDraft(draftOf(op, m.endpoint));
  }, [loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  if (mod.isPending) return <RecordSkeleton />;
  if (mod.isError)
    return (
      <PageLayout icon={Wrench} title="Tool operation" backHref="/tools">
        <QueryError what="this tool module" onRetry={() => mod.refetch()} retrying={mod.isFetching} error={mod.error} />
      </PageLayout>
    );
  if (!m || !op || !draft)
    return (
      <PageLayout icon={Wrench} title={name} backHref={`/tools/${params.id}`}>
        <EmptyState icon={SearchX} title="No such operation" description={`${m?.displayName ?? 'This module'} has no operation named ${name}.`} />
      </PageLayout>
    );

  const patch = patchOf(op, m.endpoint, draft);
  const stagedCall = m.pendingChanges.some((c) => c.operation === op.name && c.kind === 'schema_changed');
  const stage = (p: OperationPatch, what: string) =>
    update.mutateAsync({ id: m.id, operationId: op.id, patch: p }).then(
      () => (setInputErrors({}), toast.success(what, { description: 'Publish a version for agents to use it.' })),
      (e: Error) => {
        // A refused input schema names its field (input.<name>); the reason shows on that row.
        const field = e instanceof ApiError ? String(e.details?.field ?? '') : '';
        if (field.startsWith('input.')) setInputErrors({ [field.slice(6)]: e.message });
        else toast.error('Couldn’t stage the change', { description: e.message });
        throw e;
      },
    );

  return (
    <>
      <ToolWorkbench
        moduleId={m.id}
        moduleName={m.displayName}
        endpoint={m.endpoint}
        op={op}
        published={m.status === 'published'}
        draft={draft}
        onDraftChange={setDraft}
        onStage={() => void stage(patch, `Staged changes to ${op.name}`).catch(() => undefined)}
        staging={update.isPending}
        dirty={Object.keys(patch).length > 0}
        contexts={m.runContexts}
        onRun={(input) => test.mutate({ id: m.id, ...input })}
        onReset={() => test.reset()}
        running={test.isPending}
        result={test.data}
        runError={test.error?.message}
        stagedCall={stagedCall}
        inputErrors={inputErrors}
        extraActions={
          <BuilderOnly>
            <Button variant="outline" onClick={() => setPolicyOpen(true)} data-testid="workbench-policy">
              <ShieldCheck className="size-4" /> Access and approval
            </Button>
          </BuilderOnly>
        }
      />
      <OperationSheet policyOnly op={policyOpen ? op : null} endpoint={m.endpoint} stagedCall={stagedCall} onOpenChange={setPolicyOpen} saving={update.isPending} onSave={(p) => stage(p, `Staged changes to ${op.name}`)} />
    </>
  );
}
