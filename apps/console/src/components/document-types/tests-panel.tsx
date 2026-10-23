"use client";

import * as React from "react";
import {
  AlertCircle,
  CheckCircle2,
  FlaskConical,
  Loader2,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";

import { DialogShell } from "@/components/shared/dialog-shell";
import { EmptyState } from "@/components/shared/empty-state";
import { LoadingButton } from "@/components/shared/loading-button";
import { QueryError } from "@/components/shared/query-states";
import { KeyValues, Section, StatTile } from "@/components/shared/surface";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useSessionTests,
  useStartTest,
  useTestEstimate,
  useTestRun,
} from "@/hooks/document-type-queries";
import { pct, plural, relativeTime } from "@/lib/format";
import type {
  DocumentField,
  DocumentType,
  DocumentTypeTestRun,
  DocumentTypeVersion,
} from "@/lib/types/document-types";

import { fieldLabel } from "./samples-panel";

const accuracy = (n: number | null | undefined) => (n == null ? "—" : pct(n));
const value = (v: string | number | null) =>
  v == null || v === "" ? (
    <span className="text-muted-foreground">Not read</span>
  ) : (
    String(v)
  );
const cost = (c: string | null | undefined) =>
  c == null ? undefined : `$${c}`;

/** Tests of the shown version started in this session: run one, follow it, then read the score per field and per sample. */
export function TestsPanel({
  type,
  version,
}: {
  type: DocumentType;
  version: DocumentTypeVersion;
}) {
  const sessionTests = useSessionTests(type.id);
  const testId = sessionTests.data?.[version.version];
  const run = useTestRun(type.id, testId);
  const [open, setOpen] = React.useState(false);
  const busy = run.data?.status === "queued" || run.data?.status === "running";

  return (
    <div className="flex flex-col gap-4" data-testid="tests-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Reads every sample with v{version.version} and compares each field
          with the value it should read.
        </p>
        {type.canEdit && (
          <Button
            onClick={() => setOpen(true)}
            disabled={busy}
            data-testid="run-test-button"
          >
            <FlaskConical className="size-4" /> Run test
          </Button>
        )}
      </div>
      {!testId ? (
        <EmptyState
          icon={FlaskConical}
          title={`No test of v${version.version} yet`}
          description={
            type.samples.length
              ? "Run a test to see how this version reads the samples."
              : "Add a sample on the Samples tab, then run a test."
          }
          action={
            type.canEdit && type.samples.length
              ? { label: "Run test", onClick: () => setOpen(true) }
              : undefined
          }
        />
      ) : run.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : run.isError && !run.data ? (
        <QueryError
          what="the test"
          onRetry={() => run.refetch()}
          retrying={run.isFetching}
          error={run.error}
        />
      ) : (
        <TestResult run={run.data!} fields={version.fields} />
      )}
      {type.canEdit && (
        <RunTestDialog
          open={open}
          onOpenChange={setOpen}
          type={type}
          version={version.version}
        />
      )}
    </div>
  );
}

function TestResult({
  run,
  fields,
}: {
  run: DocumentTypeTestRun;
  fields: DocumentField[];
}) {
  const asked = `Started by ${run.askedBy} ${relativeTime(run.askedAt)}`;
  if (run.status === "queued" || run.status === "running")
    return (
      <Section>
        <div className="flex items-center gap-3" data-testid="test-progress">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">
              {run.status === "queued"
                ? "Waiting to start"
                : `Reading ${plural(run.samples, "sample")} with v${run.version}`}
            </p>
            <p className="text-xs text-muted-foreground">
              {asked}. Results show here when it finishes.
            </p>
          </div>
        </div>
      </Section>
    );
  if (run.status === "failed" || !run.result)
    return (
      <Alert variant="destructive">
        <AlertCircle className="size-4" />
        <AlertTitle>The test of v{run.version} failed</AlertTitle>
        <AlertDescription>
          {run.error ?? "It finished without a result."} Run it again.
        </AlertDescription>
      </Alert>
    );
  const r = run.result;
  const scored = fields.filter((f) => r.fields[f.key]);
  const totals = scored.reduce(
    (t, f) => ({
      matches: t.matches + r.fields[f.key].matches,
      misses: t.misses + r.fields[f.key].misses,
    }),
    { matches: 0, misses: 0 },
  );
  return (
    <div className="flex flex-col gap-4" data-testid="test-result">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile
          label="Accuracy"
          value={accuracy(r.accuracy)}
          hint={`v${run.version} · started by ${run.askedBy} ${relativeTime(run.askedAt)}`}
          tone={r.accuracy != null && r.accuracy < 0.9 ? "warn" : "default"}
        />
        <StatTile
          label="Values matched"
          value={totals.matches.toLocaleString("en-CA")}
          hint={`of ${plural(totals.matches + totals.misses, "value")}`}
        />
        <StatTile
          label="Samples read"
          value={r.samples.length.toLocaleString("en-CA")}
          hint={plural(
            r.samples.filter((s) => s.status !== "done").length,
            "failed read",
          )}
          tone={r.samples.some((s) => s.status !== "done") ? "bad" : "default"}
        />
      </div>
      <Section title="By field" flush>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Field</TableHead>
              <TableHead className="text-right">Matches</TableHead>
              <TableHead className="text-right">Misses</TableHead>
              <TableHead className="text-right">Accuracy</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {fields.map((f) => {
              const s = r.fields[f.key];
              return (
                <TableRow key={f.key} data-testid={`field-score-${f.key}`}>
                  <TableCell>
                    <div className="text-sm font-medium">{fieldLabel(f)}</div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {f.key}
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {s?.accuracy != null ? s.matches : "—"}
                  </TableCell>
                  <TableCell
                    className={
                      s?.misses
                        ? "text-right tabular-nums text-destructive"
                        : "text-right tabular-nums"
                    }
                  >
                    {s?.accuracy != null ? s.misses : "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {s?.accuracy == null ? (
                      <span className="text-muted-foreground">
                        No sample names it
                      </span>
                    ) : (
                      accuracy(s.accuracy)
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </Section>
      {r.samples.map((s) => {
        // A field lists one comparison per record that names it, so its position is the record only when every record does.
        const records = Math.max(
          0,
          ...Object.values(s.fields).map((l) => l.length),
        );
        return (
          <Section
            key={s.sampleId}
            title={s.name}
            description={
              s.status === "done" ? undefined : `Not read: ${s.status}`
            }
            flush
          >
            {s.status === "done" ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Field</TableHead>
                    <TableHead>Should read</TableHead>
                    <TableHead>Read</TableHead>
                    <TableHead className="w-24">Result</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {fields
                    .filter((f) => s.fields[f.key]?.length)
                    .flatMap((f) =>
                      s.fields[f.key].map((c, i) => (
                        <TableRow key={`${f.key}-${i}`}>
                          <TableCell className="text-sm">
                            {fieldLabel(f)}
                            {records > 1 &&
                              s.fields[f.key].length === records && (
                                <span className="text-muted-foreground">
                                  {" "}
                                  · record {i + 1}
                                </span>
                              )}
                          </TableCell>
                          <TableCell className="text-sm">
                            {value(c.expected)}
                          </TableCell>
                          <TableCell className="text-sm">
                            {value(c.got)}
                          </TableCell>
                          <TableCell>
                            {c.match ? (
                              <span className="inline-flex items-center gap-1 text-sm text-success-text">
                                <CheckCircle2 className="size-4" /> Match
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-sm text-destructive">
                                <XCircle className="size-4" /> Miss
                              </span>
                            )}
                          </TableCell>
                        </TableRow>
                      )),
                    )}
                </TableBody>
              </Table>
            ) : (
              <p className="px-4 py-3 text-sm text-muted-foreground">
                The file could not be read, so no field was compared.
              </p>
            )}
          </Section>
        );
      })}
    </div>
  );
}

/** Shows what the test spends before it runs: samples, model calls and cost, then starts it. */
function RunTestDialog({
  open,
  onOpenChange,
  type,
  version,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  type: DocumentType;
  version: number;
}) {
  const estimate = useTestEstimate(type.id, version, open);
  const start = useStartTest();
  const e = estimate.data;
  const run = async () => {
    try {
      await start.mutateAsync({ id: type.id, version });
      toast.success(`Testing v${version}`, {
        description: "Results show on this tab when it finishes.",
      });
      onOpenChange(false);
    } catch (err) {
      toast.error(`Couldn’t start the test of v${version}`, {
        description: (err as Error).message,
      });
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      title={`Test v${version}`}
      description="Each sample is one model call, two when the model has to be asked again."
      footer={
        <>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <LoadingButton
            isLoading={start.isPending}
            loadingText="Starting…"
            disabled={!e || e.samples === 0}
            onClick={run}
            data-testid="start-test"
          >
            {e ? `Run on ${plural(e.samples, "sample")}` : "Run test"}
          </LoadingButton>
        </>
      }
    >
      {estimate.isPending ? (
        <div className="flex flex-col gap-2" data-testid="estimate-loading">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-6 w-full" />
          ))}
        </div>
      ) : estimate.isError || !e ? (
        <QueryError
          what="the estimate"
          onRetry={() => estimate.refetch()}
          retrying={estimate.isFetching}
          error={estimate.error}
        />
      ) : (
        <div className="flex flex-col gap-3" data-testid="test-estimate">
          <KeyValues
            rows={[
              ["Samples", plural(e.samples, "sample")],
              ["Model calls", plural(e.calls, "call")],
              ["Calls at most", plural(e.maxCalls, "call")],
              ["Estimated cost", cost(e.estimatedCost) ?? "Cost unknown"],
              [
                "Cost at most",
                e.estimatedCost == null
                  ? "Cost unknown"
                  : (cost(e.maxCost) ?? "Cost unknown"),
              ],
              ["Model", e.alias],
            ]}
          />
          <p className="text-xs text-muted-foreground">
            A test reads at most {plural(e.capped, "sample")}
            {type.samples.length > e.capped
              ? `; this type has ${type.samples.length}, so the first ${e.capped} are read.`
              : "."}
          </p>
          {e.samples === 0 && (
            <p className="text-sm text-destructive">
              Add a sample on the Samples tab first.
            </p>
          )}
        </div>
      )}
    </DialogShell>
  );
}
