"use client";

import * as React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { ExternalLink, FileText } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { DataTableColumnHeader } from "@/components/data-table-column-header";
import { DataTableRowActions } from "@/components/data-table-row-actions";
import { DataTableWithViews } from "@/components/data-table-with-views";
import {
  emptyVersionDraft,
  hasVersionErrors,
  VersionFieldsEditor,
  versionErrors,
  versionInput,
  type VersionDraft,
  type VersionDraftErrors,
} from "@/components/document-types/field-editor-dialog";
import { PageLayout } from "@/components/page-layout";
import { DialogShell } from "@/components/shared/dialog-shell";
import { FormField, StopRowClick } from "@/components/shared/form-field";
import { LoadingButton } from "@/components/shared/loading-button";
import { PageSkeleton } from "@/components/shared/page-skeleton";
import { ListEmpty, QueryError } from "@/components/shared/query-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  useCreateDocumentType,
  useDocumentTypes,
} from "@/hooks/document-type-queries";
import type {
  DocumentType,
  DocumentTypeSummary,
} from "@/lib/types/document-types";

const ID = /^[a-z][a-z0-9_]{2,63}$/;

function columns(
  open: (t: DocumentTypeSummary) => void,
): ColumnDef<DocumentTypeSummary>[] {
  return [
    {
      accessorKey: "name",
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Document type" />
      ),
      cell: ({ row }) => (
        <div className="min-w-48">
          <div className="text-sm font-medium">{row.original.name}</div>
          {row.original.description && (
            <div className="text-xs text-muted-foreground">
              {row.original.description}
            </div>
          )}
        </div>
      ),
      enableHiding: false,
    },
    {
      id: "id",
      header: "Id",
      cell: ({ row }) => (
        <span className="font-mono text-xs text-muted-foreground">
          {row.original.id}
        </span>
      ),
    },
    {
      accessorKey: "latestVersion",
      header: ({ column }) => (
        <DataTableColumnHeader column={column} title="Newest version" />
      ),
      cell: ({ row }) => (
        <Badge variant="outline">v{row.original.latestVersion}</Badge>
      ),
    },
    {
      id: "actions",
      meta: {
        className:
          "sticky right-0 z-[1] w-10 bg-card shadow-[-8px_0_8px_-8px_rgb(0_0_0/0.12)]",
      },
      cell: ({ row }) => (
        <StopRowClick>
          <DataTableRowActions
            row={row}
            actions={[
              {
                label: "Open",
                icon: ExternalLink,
                onClick: () => open(row.original),
              },
            ]}
          />
        </StopRowClick>
      ),
      enableHiding: false,
    },
  ];
}

/** Create a document type: its name, an optional id, and the fields of its first version. It opens on its own page. */
function NewTypeDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (t: DocumentType) => void;
}) {
  const create = useCreateDocumentType();
  const [name, setName] = React.useState("");
  const [typeId, setTypeId] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [draft, setDraft] = React.useState<VersionDraft>(emptyVersionDraft);
  const [errors, setErrors] = React.useState<
    VersionDraftErrors & { name?: string; id?: string; submit?: string }
  >({});
  React.useEffect(() => {
    if (!open) return;
    setName("");
    setTypeId("");
    setDescription("");
    setDraft(emptyVersionDraft());
    setErrors({});
  }, [open]);
  const submit = async () => {
    const id = typeId.trim();
    const e = {
      ...versionErrors(draft),
      name: name.trim() ? undefined : "Name the document type.",
      id:
        !id || ID.test(id)
          ? undefined
          : "3 to 64 lowercase letters, digits and underscores, starting with a letter.",
    };
    setErrors(e);
    if (e.name || e.id || hasVersionErrors(e)) return;
    try {
      const saved = await create.mutateAsync({
        ...versionInput(draft),
        name: name.trim(),
        ...(id ? { id } : {}),
        ...(description.trim() ? { description: description.trim() } : {}),
      });
      toast.success(`Created ${saved.name}`, {
        description: "Add samples, then run a test of v1.",
      });
      onOpenChange(false);
      onCreated(saved);
    } catch (err) {
      setErrors({ submit: (err as Error).message });
    }
  };
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title="New document type"
      description="The fields to read from this kind of document. Saving makes v1; later changes save new versions."
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
              isLoading={create.isPending}
              loadingText="Creating…"
              data-testid="create-document-type"
            >
              Create type
            </LoadingButton>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid gap-4 md:grid-cols-2">
          <FormField id="document-type-name" label="Name" error={errors.name}>
            <Input
              id="document-type-name"
              value={name}
              aria-invalid={!!errors.name}
              onChange={(e) => (setName(e.target.value), setErrors({}))}
              placeholder="e.g. Garnishment order"
            />
          </FormField>
          <FormField
            id="document-type-id"
            label="Id"
            optional
            error={errors.id}
            hint="Workflows name the type by its id. Left empty, one is made for you."
          >
            <Input
              id="document-type-id"
              value={typeId}
              aria-invalid={!!errors.id}
              onChange={(e) => (setTypeId(e.target.value), setErrors({}))}
              placeholder="e.g. garnishment_order"
              className="font-mono"
            />
          </FormField>
        </div>
        <FormField id="document-type-description" label="Description" optional>
          <Input
            id="document-type-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. A court order to pay part of an account holder’s funds"
          />
        </FormField>
        <VersionFieldsEditor
          value={draft}
          onChange={(d) => (setDraft(d), setErrors({}))}
          errors={errors}
        />
      </div>
    </DialogShell>
  );
}

export default function DocumentTypesPage() {
  const router = useRouter();
  const query = useDocumentTypes();
  const [creating, setCreating] = React.useState(false);
  const [filterResetKey, setFilterResetKey] = React.useState(0);
  const [filtered, setFiltered] = React.useState(false);
  const canCreate = !!query.data?.canCreate;
  const cols = React.useMemo(
    () => columns((t) => router.push(`/document-types/${t.id}`)),
    [router],
  );

  return (
    <PageLayout
      switcher
      icon={FileText}
      title="Document types"
      description="The fields agents and workflows read from each kind of document, versioned and tested against sample files."
      actions={
        canCreate && (
          <Button
            onClick={() => setCreating(true)}
            data-testid="new-document-type-button"
          >
            New type
          </Button>
        )
      }
    >
      {query.isPending ? (
        <PageSkeleton statCards={0} tableRows={4} />
      ) : query.isError && !query.data ? (
        <QueryError
          what="document types"
          onRetry={() => query.refetch()}
          retrying={query.isFetching}
          error={query.error}
        />
      ) : (
        <DataTableWithViews
          columns={cols}
          data={query.data.items.map((t) => ({
            ...t,
            onRowClick: (x: DocumentTypeSummary) =>
              router.push(`/document-types/${x.id}`),
            href: `/document-types/${t.id}`,
          }))}
          getRowId={(t) => t.id}
          searchColumn="name"
          searchPlaceholder="Search document types…"
          filterResetKey={filterResetKey}
          onColumnFiltersChange={(f) =>
            setFiltered(
              f.some((x) =>
                Array.isArray(x.value) ? x.value.length > 0 : !!x.value,
              ),
            )
          }
          hideViewSwitcher
          emptyState={
            <ListEmpty
              icon={FileText}
              noun="document types"
              filtered={filtered}
              onClear={() => setFilterResetKey((k) => k + 1)}
              createLabel={canCreate ? "New type" : undefined}
              onCreate={() => setCreating(true)}
              description="Name the fields to read from a kind of document, add sample files, and test how well each version reads them."
            />
          }
        />
      )}
      {canCreate && (
        <NewTypeDialog
          open={creating}
          onOpenChange={setCreating}
          onCreated={(t) => router.push(`/document-types/${t.id}`)}
        />
      )}
    </PageLayout>
  );
}
