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
import { ToolTabs } from '@/components/tools/tool-tabs';
import { UsedBySection } from '@/components/tools/used-by';
import { RestTool } from '@/components/tools/rest-tool';
import { baseOfApp, draftOf, patchOf, ToolWorkbench, type WorkbenchDraft } from '@/components/tools/tool-workbench';
import { Button } from '@/components/ui/button';
import { useToolRow } from '@/hooks/queries';
import { useConnectionOptions } from '@/hooks/systems-queries';
import { useSetModuleConnection, useTestModule, useToolModule, useUpdateOperation } from '@/hooks/tool-module-queries';
import { ApiError } from '@/lib/api/contract';
import type { IntegrationStatus } from '@/lib/types/integrations';
import type { ModuleTestInput, OperationPatch } from '@/lib/types/tool-modules';

/** One tool operation on its own page (c-088): edit its call, inputs, mock and transform, and try them before staging. A
 * REST operation is laid out as an API client lays out a request (c-591). */
export default function OperationWorkbenchPage() {
  const params = useParams<{ id: string; op: string }>();
  const name = decodeURIComponent(params.op);
  const mod = useToolModule(params.id);
  // Who uses this tool, joined by the API: the agents granted it and the workflows that call it.
  const usedBy = useToolRow(name);
  const test = useTestModule();
  const update = useUpdateOperation();
  const [policyOpen, setPolicyOpen] = React.useState(false);
  const [inputErrors, setInputErrors] = React.useState<Record<string, string>>({});
  const [saveProblems, setSaveProblems] = React.useState<string[]>([]);
  const setConnection = useSetModuleConnection();
  const connections = useConnectionOptions();
  const m = mod.data;
  const op = m?.operations.find((o) => o.name === name);
  const [draft, setDraft] = React.useState<WorkbenchDraft | null>(null);
  // A fresh definition after staging (or another tab's edit) replaces the draft; typing in between is kept.
  // The address comes from the app's connection, never the module (c-616): its base address per environment.
  const base = baseOfApp(m?.connection);
  const loaded = op && m ? JSON.stringify(draftOf(op, base)) : '';
  React.useEffect(() => {
    if (op && m) setDraft(draftOf(op, base));
  }, [loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  if (mod.isPending) return <RecordSkeleton />;
  if (mod.isError)
    return (
      <PageLayout icon={Wrench} title="Tool operation" backHref="/tools">
        <QueryError what="these tools" onRetry={() => mod.refetch()} retrying={mod.isFetching} error={mod.error} />
      </PageLayout>
    );
  if (!m || !op || !draft)
    return (
      <PageLayout icon={Wrench} title={name} backHref={`/tools/${params.id}`}>
        <EmptyState icon={SearchX} title="No such operation" description={`${m?.displayName ?? 'These tools'} has no operation named ${name}.`} />
      </PageLayout>
    );

  const patch = patchOf(op, base, draft);
  const stagedCall = m.pendingChanges.some((c) => c.operation === op.name && c.kind === 'schema_changed');
  const stage = (p: OperationPatch, what: string) =>
    update.mutateAsync({ id: m.id, operationId: op.id, patch: p }).then(
      () => (setInputErrors({}), setSaveProblems([]), toast.success(what, { description: 'Publish a version for agents to use it.' })),
      (e: Error) => {
        // A refused input schema names its field (input.<name>); the reason shows on that row. A refused call lists every
        // problem at once (details.problems), shown together above the request.
        const field = e instanceof ApiError ? String(e.details?.field ?? '') : '';
        const problems = e instanceof ApiError && Array.isArray(e.details?.problems) ? (e.details.problems as string[]) : [];
        if (field.startsWith('input.')) setInputErrors({ [field.slice(6)]: e.message });
        else if (problems.length && op.executor === 'http') setSaveProblems(problems);
        else toast.error('Couldn’t stage the change', { description: e.message });
        throw e;
      },
    );

  const policy = (
    <BuilderOnly>
      <Button variant="outline" onClick={() => setPolicyOpen(true)} data-testid="workbench-policy">
        <ShieldCheck className="size-4" /> Access and approval
      </Button>
    </BuilderOnly>
  );
  const run = {
    onRun: (input: ModuleTestInput) => test.mutate({ id: m.id, ...input }),
    onReset: () => test.reset(),
    running: test.isPending,
    result: test.data,
    runError: test.error?.message,
  };

  return (
    <>
      {op.executor === 'http' ? (
        <RestTool
          tabs={<ToolTabs moduleId={m.id} operation={op.name} />}
          aside={<UsedBySection row={usedBy} />}
          moduleId={m.id}
          moduleName={m.displayName}
          base={base}
          op={op}
          published={m.status === 'published'}
          draft={draft}
          onDraftChange={setDraft}
          onSave={() => void stage(patch, `Saved ${op.name}`).catch(() => undefined)}
          saving={update.isPending}
          dirty={Object.keys(patch).length > 0}
          saveProblems={saveProblems}
          connection={m.connection}
          connections={connections.data?.data.map((c) => ({ id: c.id, name: c.name, status: c.status as IntegrationStatus }))}
          connectionsLoading={connections.isPending}
          settingConnection={setConnection.isPending}
          onConnectionChange={(connectionId) =>
            setConnection.mutate(
              { id: m.id, connectionId },
              { onSuccess: (x) => toast.success(`Calls ${x.connection?.name} now`), onError: (e) => toast.error('Couldn’t change the app', { description: e.message }) },
            )
          }
          stagedCall={stagedCall}
          inputErrors={inputErrors}
          extraActions={policy}
          {...run}
        />
      ) : (
      <ToolWorkbench
        tabs={<ToolTabs moduleId={m.id} operation={op.name} />}
        aside={<UsedBySection row={usedBy} />}
        moduleId={m.id}
        moduleName={m.displayName}
        base={base}
        op={op}
        published={m.status === 'published'}
        draft={draft}
        onDraftChange={setDraft}
        onStage={() => void stage(patch, `Staged changes to ${op.name}`).catch(() => undefined)}
        staging={update.isPending}
        dirty={Object.keys(patch).length > 0}
        contexts={m.runContexts}
        {...run}
        stagedCall={stagedCall}
        inputErrors={inputErrors}
        extraActions={policy}
      />
      )}
      <OperationSheet policyOnly op={policyOpen ? op : null} base={base} stagedCall={stagedCall} onOpenChange={setPolicyOpen} saving={update.isPending} onSave={(p) => stage(p, `Staged changes to ${op.name}`)} />
    </>
  );
}
