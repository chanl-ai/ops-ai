"use client";

import * as React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { FileText, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";

import { DataTableColumnHeader } from "@/components/data-table-column-header";
import { DataTableWithViews } from "@/components/data-table-with-views";
import { DeleteDialog } from "@/components/shared/delete-dialog";
import { DialogShell } from "@/components/shared/dialog-shell";
import { EntityPicker } from "@/components/shared/entity-picker";
import { FormFieldGroup, StopRowClick } from "@/components/shared/form-field";
import { LoadingButton } from "@/components/shared/loading-button";
import { ListEmpty } from "@/components/shared/query-states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAddSample, useRemoveSample } from "@/hooks/document-type-queries";
import { fileOptions } from "@/hooks/options-queries";
import { plural, relativeTime } from "@/lib/format";
import type {
  DocumentField,
  DocumentType,
  DocumentTypeSample,
  DocumentTypeVersion,
  ExpectedRecord,
} from "@/lib/types/document-types";

export const fieldLabel = (f: DocumentField) => f.label || f.key;

const recordsOf = (s: DocumentTypeSample): ExpectedRecord[] =>
  Array.isArray(s.expected) ? s.expected : [s.expected];

/** A line saying what the sample should read: each record's first value, or the first few values of a single record. */
function expectedSummary(s: DocumentTypeSample, fields: DocumentField[]) {
  const records = recordsOf(s);
  const shown = (r: ExpectedRecord) =>
    fields.find((f) => r[f.key] != null && r[f.key] !== "");
  if (records.length > 1)
    return `${plural(records.length, "record")} · ${records
      .map((r) => {
        const f = shown(r);
        return f ? String(r[f.key]) : "—";
      })
      .join(", ")}`;
  const r = records[0] ?? {};
  const parts = fields
    .filter((f) => r[f.key] != null && r[f.key] !== "")
    .slice(0, 3);
  return parts.length
    ? parts.map((f) => `${fieldLabel(f)}: ${r[f.key]}`).join(" · ")
    : "No values";
}

/** The type's sample files and the values each should read; tests compare every version against them. */
export function SamplesPanel({
  type,
  latest,
}: {
  type: DocumentType;
  latest: DocumentTypeVersion;
}) {
  const [adding, setAdding] = React.useState(false);
  const [removing, setRemoving] = React.useState<DocumentTypeSample | null>(
    null,
  );
  const remove = useRemoveSample();
  const columns = React.useMemo<ColumnDef<DocumentTypeSample>[]>(
    () => [
      {
        accessorKey: "name",
        header: ({ column }) => (
          <DataTableColumnHeader column={column} title="File" />
        ),
        cell: ({ row }) => (
          <div className="min-w-48">
            <div className="text-sm font-medium">{row.original.name}</div>
            <div className="text-xs text-muted-foreground">
              Added by {row.original.addedBy} ·{" "}
              {relativeTime(row.original.addedAt)}
            </div>
          </div>
        ),
        enableHiding: false,
      },
      {
        id: "expected",
        header: "Should read",
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {expectedSummary(row.original, latest.fields)}
          </span>
        ),
      },
      ...(type.canEdit
        ? [
            {
              id: "actions",
              meta: { className: "w-10" },
              cell: ({ row }) => (
                <StopRowClick>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove ${row.original.name}`}
                    onClick={() => setRemoving(row.original)}
                    data-testid={`remove-sample-${row.original.id}`}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </StopRowClick>
              ),
              enableHiding: false,
            } satisfies ColumnDef<DocumentTypeSample>,
          ]
        : []),
    ],
    [latest.fields, type.canEdit],
  );

  return (
    <div className="flex flex-col gap-3" data-testid="samples-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Files from your team with the values each should read. Every test
          reads them with the version it tests.
        </p>
        {type.canEdit && (
          <Button
            onClick={() => setAdding(true)}
            data-testid="add-sample-button"
          >
            <Plus className="size-4" /> Add sample
          </Button>
        )}
      </div>
      <DataTableWithViews
        columns={columns}
        data={type.samples}
        getRowId={(s) => s.id}
        searchColumn="name"
        searchPlaceholder="Search files…"
        hideViewSwitcher
        emptyState={
          <ListEmpty
            icon={FileText}
            noun="samples"
            filtered={false}
            createLabel={type.canEdit ? "Add sample" : undefined}
            onCreate={() => setAdding(true)}
            description="Add a file with the values it should read, then run a test."
          />
        }
      />
      {type.canEdit && (
        <AddSampleDialog
          open={adding}
          onOpenChange={setAdding}
          type={type}
          latest={latest}
        />
      )}
      <DeleteDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        entityType="sample"
        entityName={removing?.name}
        verb="Remove"
        description="Tests stop reading this file. The file stays in Files."
        confirmText="Remove sample"
        isLoading={remove.isPending}
        onConfirm={async () => {
          try {
            await remove.mutateAsync({ id: type.id, sampleId: removing!.id });
            toast.success(`Removed ${removing!.name}`);
            setRemoving(null);
          } catch (e) {
            toast.error(`Couldn’t remove ${removing!.name}`, {
              description: (e as Error).message,
            });
          }
        }}
      />
    </div>
  );
}

type RecordDraft = Record<string, string>;

/** A typed value as the field's type: numbers and money as numbers when they parse, empty cells left out. */
function expectedRecord(
  fields: DocumentField[],
  r: RecordDraft,
): ExpectedRecord {
  const out: ExpectedRecord = {};
  for (const f of fields) {
    const t = (r[f.key] ?? "").trim();
    if (!t) continue;
    const n = Number(t.replace(/,/g, ""));
    out[f.key] =
      (f.type === "number" || f.type === "money") && !Number.isNaN(n) ? n : t;
  }
  return out;
}

/** One row per field, one column per record the file holds. */
function ExpectedValuesEditor({
  fields,
  many,
  records,
  onChange,
}: {
  fields: DocumentField[];
  many: boolean;
  records: RecordDraft[];
  onChange: (r: RecordDraft[]) => void;
}) {
  const set = (ri: number, key: string, value: string) =>
    onChange(records.map((r, n) => (n === ri ? { ...r, [key]: value } : r)));
  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Field</TableHead>
              {records.map((_, ri) => (
                <TableHead key={ri} className="min-w-44">
                  {many ? (
                    <div className="flex items-center justify-between gap-1">
                      <span>Record {ri + 1}</span>
                      {records.length > 1 && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-7"
                          aria-label={`Remove record ${ri + 1}`}
                          onClick={() =>
                            onChange(records.filter((_, n) => n !== ri))
                          }
                        >
                          <X className="size-3.5" />
                        </Button>
                      )}
                    </div>
                  ) : (
                    "Should read"
                  )}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {fields.map((f) => (
              <TableRow key={f.key}>
                <TableCell className="min-w-36 align-top">
                  <div className="text-sm font-medium">
                    {fieldLabel(f)}
                    {f.required && (
                      <span className="text-muted-foreground"> *</span>
                    )}
                  </div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {f.key}
                  </div>
                </TableCell>
                {records.map((r, ri) => {
                  const label = `${fieldLabel(f)}${many ? `, record ${ri + 1}` : ""}`;
                  return (
                    <TableCell key={ri} className="align-top">
                      {f.type === "enum" ? (
                        <Select
                          value={r[f.key] ?? ""}
                          onValueChange={(v) => set(ri, f.key, v)}
                        >
                          <SelectTrigger
                            aria-label={label}
                            className="w-full text-xs"
                          >
                            <SelectValue placeholder="Choose" />
                          </SelectTrigger>
                          <SelectContent>
                            {(f.options ?? []).map((o) => (
                              <SelectItem key={o} value={o}>
                                {o}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : (
                        <Input
                          aria-label={label}
                          type={f.type === "date" ? "date" : "text"}
                          inputMode={
                            f.type === "number" || f.type === "money"
                              ? "decimal"
                              : undefined
                          }
                          value={r[f.key] ?? ""}
                          onChange={(e) => set(ri, f.key, e.target.value)}
                          placeholder={
                            f.type === "money"
                              ? "e.g. 1250.00"
                              : f.type === "number"
                                ? "e.g. 3"
                                : undefined
                          }
                          className="text-xs"
                        />
                      )}
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {many && (
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange([...records, {}])}
            data-testid="add-record"
          >
            <Plus className="size-4" /> Add record
          </Button>
        </div>
      )}
    </div>
  );
}

/** Pick one of the team's files and type the values it should read, against the newest version's fields. */
function AddSampleDialog({
  open,
  onOpenChange,
  type,
  latest,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  type: DocumentType;
  latest: DocumentTypeVersion;
}) {
  const add = useAddSample();
  const [fileIds, setFileIds] = React.useState<string[]>([]);
  const [records, setRecords] = React.useState<RecordDraft[]>([{}]);
  const [errors, setErrors] = React.useState<{
    file?: string;
    values?: string;
    submit?: string;
  }>({});
  React.useEffect(() => {
    if (!open) return;
    setFileIds([]);
    setRecords([{}]);
    setErrors({});
  }, [open]);
  const submit = async () => {
    const expected = records.map((r) => expectedRecord(latest.fields, r));
    const e = {
      file: fileIds.length ? undefined : "Pick the file.",
      values: expected.some((r) => !Object.keys(r).length)
        ? latest.many
          ? "Fill in at least one value for each record."
          : "Fill in at least one value."
        : undefined,
    };
    setErrors(e);
    if (e.file || e.values) return;
    try {
      const saved = await add.mutateAsync({
        id: type.id,
        input: {
          fileId: fileIds[0],
          expected: latest.many ? expected : expected[0],
        },
      });
      toast.success(`Added ${saved.name}`, {
        description: "Run a test to see how each version reads it.",
      });
      onOpenChange(false);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Add sample"
      description={`Values are checked against v${latest.version}, the newest version.`}
      onSubmit={submit}
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-destructive">{errors.submit}</p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <LoadingButton
              type="submit"
              isLoading={add.isPending}
              loadingText="Adding…"
              data-testid="add-sample-submit"
            >
              Add sample
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-5">
        <FormFieldGroup
          label="File"
          error={errors.file}
          hint="A file in your team that has been scanned clean."
        >
          <EntityPicker
            source={fileOptions}
            value={fileIds}
            onChange={(ids) => (setFileIds(ids), setErrors({}))}
            multiple={false}
            addLabel={fileIds.length ? "Pick another file" : "Pick from Files"}
            searchPlaceholder="Search your team's files by name…"
            emptyText="No file matches. Upload it in Files first."
            icon={FileText}
            testId="sample-file-picker"
          />
        </FormFieldGroup>
        <FormFieldGroup
          label={
            latest.many ? "Values for each record" : "Values it should read"
          }
          error={errors.values}
          hint="Leave a value empty when the file does not show it."
        >
          <ExpectedValuesEditor
            fields={latest.fields}
            many={latest.many}
            records={records}
            onChange={(r) => (setRecords(r), setErrors({}))}
          />
        </FormFieldGroup>
      </div>
    </DialogShell>
  );
}
