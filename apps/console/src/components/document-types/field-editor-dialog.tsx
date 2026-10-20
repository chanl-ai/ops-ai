"use client";

import * as React from "react";
import { Plus, Trash2 } from "lucide-react";

import { DialogShell } from "@/components/shared/dialog-shell";
import { FormField } from "@/components/shared/form-field";
import { LoadingButton } from "@/components/shared/loading-button";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type {
  DocumentField,
  DocumentFieldType,
  DocumentTypeVersion,
  DocumentTypeVersionInput,
} from "@/lib/types/document-types";

export const FIELD_TYPE_LABELS: Record<DocumentFieldType, string> = {
  text: "Text",
  number: "Number",
  money: "Money",
  date: "Date",
  enum: "One of a list",
};
const TYPES = Object.keys(FIELD_TYPE_LABELS) as DocumentFieldType[];
const KEY = /^[a-z0-9_]+$/;

/** One field as typed: options and the review threshold stay text until saved, so half-typed values are kept. */
export interface FieldDraft {
  key: string;
  label: string;
  type: DocumentFieldType;
  required: boolean;
  options: string;
  reviewBelow: string;
  /** Kept from the version the draft started from; not edited here. */
  description?: string;
  alwaysReview?: boolean;
}

/** The fields, the several-records switch and the type-wide review threshold of one version, as typed. */
export interface VersionDraft {
  fields: FieldDraft[];
  many: boolean;
  reviewBelow: string;
}

export interface VersionDraftErrors {
  fields?: string;
  rows?: Record<number, string>;
  reviewBelow?: string;
}

const blankField = (): FieldDraft => ({
  key: "",
  label: "",
  type: "text",
  required: false,
  options: "",
  reviewBelow: "",
});

export const emptyVersionDraft = (): VersionDraft => ({
  fields: [blankField()],
  many: false,
  reviewBelow: "",
});

export const versionDraft = (v: DocumentTypeVersion): VersionDraft => ({
  fields: v.fields.map((f) => ({
    key: f.key,
    label: f.label ?? "",
    type: f.type,
    required: !!f.required,
    options: (f.options ?? []).join(", "),
    reviewBelow: f.reviewBelow == null ? "" : String(f.reviewBelow),
    description: f.description,
    alwaysReview: f.alwaysReview,
  })),
  many: v.many,
  reviewBelow: v.reviewBelow == null ? "" : String(v.reviewBelow),
});

const confidence = (text: string) => {
  const t = text.trim();
  if (!t) return { value: undefined, ok: true };
  const n = Number(t);
  return { value: n, ok: !Number.isNaN(n) && n >= 0 && n <= 1 };
};
const optionsOf = (text: string) =>
  text
    .split(",")
    .map((o) => o.trim())
    .filter(Boolean);

export function versionErrors(d: VersionDraft): VersionDraftErrors {
  const rows: Record<number, string> = {};
  const seen = new Set<string>();
  d.fields.forEach((f, i) => {
    const key = f.key.trim();
    if (!key) rows[i] = "Give the field a key.";
    else if (!KEY.test(key))
      rows[i] = "Keys use lowercase letters, digits and underscores.";
    else if (seen.has(key)) rows[i] = `${key} is used twice.`;
    else if (f.type === "enum" && !optionsOf(f.options).length)
      rows[i] = "List the allowed values.";
    else if (!confidence(f.reviewBelow).ok)
      rows[i] = "Review below is between 0 and 1.";
    seen.add(key);
  });
  return {
    fields: d.fields.length ? undefined : "Add at least one field.",
    rows: Object.keys(rows).length ? rows : undefined,
    reviewBelow: confidence(d.reviewBelow).ok
      ? undefined
      : "Enter a confidence between 0 and 1.",
  };
}

export const hasVersionErrors = (e: VersionDraftErrors) =>
  !!(e.fields || e.rows || e.reviewBelow);

export function versionInput(d: VersionDraft): DocumentTypeVersionInput {
  const fields: DocumentField[] = d.fields.map((f) => {
    const below = confidence(f.reviewBelow).value;
    return {
      key: f.key.trim(),
      type: f.type,
      ...(f.label.trim() ? { label: f.label.trim() } : {}),
      ...(f.required ? { required: true } : {}),
      ...(f.description ? { description: f.description } : {}),
      ...(f.type === "enum" ? { options: optionsOf(f.options) } : {}),
      ...(below !== undefined ? { reviewBelow: below } : {}),
      ...(f.alwaysReview ? { alwaysReview: true } : {}),
    };
  });
  return {
    fields,
    many: d.many,
    reviewBelow: confidence(d.reviewBelow).value ?? null,
  };
}

/** Rows of fields edited in place, the "Several records" switch and the review threshold for the whole document. */
export function VersionFieldsEditor({
  value,
  onChange,
  errors,
}: {
  value: VersionDraft;
  onChange: (d: VersionDraft) => void;
  errors?: VersionDraftErrors;
}) {
  const set = (i: number, p: Partial<FieldDraft>) =>
    onChange({
      ...value,
      fields: value.fields.map((f, n) => (n === i ? { ...f, ...p } : f)),
    });
  return (
    <div className="flex flex-col gap-4" data-testid="field-editor">
      <div className="flex flex-col gap-2">
        <Label>Fields</Label>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Key</TableHead>
              <TableHead>Label</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Required</TableHead>
              <TableHead>Allowed values</TableHead>
              <TableHead>Review below</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {value.fields.map((f, i) => {
              const error = errors?.rows?.[i];
              return (
                <TableRow key={i} data-testid={`field-row-${i}`}>
                  <TableCell className="min-w-36 align-top">
                    <Input
                      aria-label={`Field ${i + 1} key`}
                      value={f.key}
                      onChange={(e) => set(i, { key: e.target.value })}
                      placeholder="e.g. case_no"
                      className="font-mono text-xs"
                      aria-invalid={!!error}
                    />
                    {error && (
                      <p className="mt-1 text-xs text-destructive">{error}</p>
                    )}
                  </TableCell>
                  <TableCell className="min-w-36 align-top">
                    <Input
                      aria-label={`Field ${i + 1} label`}
                      value={f.label}
                      onChange={(e) => set(i, { label: e.target.value })}
                      placeholder="e.g. Case number"
                      className="text-xs"
                    />
                  </TableCell>
                  <TableCell className="min-w-32 align-top">
                    <Select
                      value={f.type}
                      onValueChange={(v) =>
                        set(i, { type: v as DocumentFieldType })
                      }
                    >
                      <SelectTrigger
                        aria-label={`Field ${i + 1} type`}
                        className="w-full text-xs"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {TYPES.map((t) => (
                          <SelectItem key={t} value={t}>
                            {FIELD_TYPE_LABELS[t]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="align-top">
                    <Checkbox
                      aria-label={`Field ${i + 1} required`}
                      checked={f.required}
                      onCheckedChange={(v) => set(i, { required: v === true })}
                      className="mt-2"
                    />
                  </TableCell>
                  <TableCell className="min-w-36 align-top">
                    <Input
                      aria-label={`Field ${i + 1} allowed values`}
                      value={f.options}
                      onChange={(e) => set(i, { options: e.target.value })}
                      disabled={f.type !== "enum"}
                      placeholder={
                        f.type === "enum" ? "e.g. CAD, USD" : "Lists only"
                      }
                      className="text-xs"
                    />
                  </TableCell>
                  <TableCell className="min-w-24 align-top">
                    <Input
                      aria-label={`Field ${i + 1} review below`}
                      value={f.reviewBelow}
                      onChange={(e) => set(i, { reviewBelow: e.target.value })}
                      inputMode="decimal"
                      placeholder="e.g. 0.9"
                      className="text-xs"
                    />
                  </TableCell>
                  <TableCell className="align-top">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={`Remove ${f.key || `field ${i + 1}`}`}
                      disabled={value.fields.length === 1}
                      onClick={() =>
                        onChange({
                          ...value,
                          fields: value.fields.filter((_, n) => n !== i),
                        })
                      }
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              onChange({ ...value, fields: [...value.fields, blankField()] })
            }
            data-testid="add-field"
          >
            <Plus className="size-4" /> Add field
          </Button>
        </div>
        {errors?.fields ? (
          <p className="text-xs text-destructive">{errors.fields}</p>
        ) : (
          <p className="text-xs text-muted-foreground">
            A read below a field’s confidence goes to a person in Reviews. Leave
            it empty to use the document’s threshold.
          </p>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex items-start justify-between gap-3 rounded-lg border px-4 py-3">
          <div className="flex flex-col gap-0.5">
            <Label htmlFor="field-editor-many">Several records</Label>
            <p className="text-xs text-muted-foreground">
              One document can name several people or accounts, each read as its
              own record.
            </p>
          </div>
          <Switch
            id="field-editor-many"
            checked={value.many}
            onCheckedChange={(many) => onChange({ ...value, many })}
            data-testid="field-editor-many"
          />
        </div>
        <FormField
          id="field-editor-review-below"
          label="Review below"
          optional
          error={errors?.reviewBelow}
          hint="A confidence between 0 and 1 for every field without its own."
        >
          <Input
            id="field-editor-review-below"
            value={value.reviewBelow}
            onChange={(e) =>
              onChange({ ...value, reviewBelow: e.target.value })
            }
            inputMode="decimal"
            placeholder="e.g. 0.8"
            aria-invalid={!!errors?.reviewBelow}
          />
        </FormField>
      </div>
    </div>
  );
}

/** Save a new version of a type's fields, starting from the version on screen. Earlier versions never change. */
export function FieldEditorDialog({
  open,
  onOpenChange,
  typeName,
  from,
  nextVersion,
  saving,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  typeName: string;
  /** The version the form starts from. */
  from: DocumentTypeVersion;
  nextVersion: number;
  saving: boolean;
  /** Resolves when saved; a thrown error shows in the dialog. */
  onSave: (input: DocumentTypeVersionInput) => Promise<void>;
}) {
  const [draft, setDraft] = React.useState<VersionDraft>(() =>
    versionDraft(from),
  );
  const [note, setNote] = React.useState("");
  const [errors, setErrors] = React.useState<
    VersionDraftErrors & { submit?: string }
  >({});
  React.useEffect(() => {
    if (!open) return;
    setDraft(versionDraft(from));
    setNote("");
    setErrors({});
    // Reset when the dialog opens or the starting version changes, not when a refetch hands over an equal object.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, from.version]);
  const submit = async () => {
    const e = versionErrors(draft);
    setErrors(e);
    if (hasVersionErrors(e)) return;
    try {
      await onSave({
        ...versionInput(draft),
        ...(note.trim() ? { note: note.trim() } : {}),
      });
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title={`New version of ${typeName}`}
      description={`Starts from v${from.version}. Saving makes v${nextVersion}; extractions that name an earlier version keep reading with it.`}
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
              isLoading={saving}
              loadingText="Saving…"
              data-testid="save-version"
            >
              Save v{nextVersion}
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <VersionFieldsEditor
          value={draft}
          onChange={(d) => (setDraft(d), setErrors({}))}
          errors={errors}
        />
        <FormField
          id="field-editor-note"
          label="What changed"
          optional
          hint="Shown beside the version in the picker."
        >
          <Input
            id="field-editor-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Added the currency"
          />
        </FormField>
      </div>
    </DialogShell>
  );
}
