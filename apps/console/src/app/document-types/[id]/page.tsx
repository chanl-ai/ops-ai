"use client";

import * as React from "react";
import { useParams } from "next/navigation";
import { FileText, Plus, SearchX } from "lucide-react";
import { toast } from "sonner";

import {
  FIELD_TYPE_LABELS,
  FieldEditorDialog,
} from "@/components/document-types/field-editor-dialog";
import {
  fieldLabel,
  SamplesPanel,
} from "@/components/document-types/samples-panel";
import { TestsPanel } from "@/components/document-types/tests-panel";
import { PageLayout } from "@/components/page-layout";
import { EmptyState } from "@/components/shared/empty-state";
import { PageSkeleton } from "@/components/shared/page-skeleton";
import { QueryError } from "@/components/shared/query-states";
import { Section } from "@/components/shared/surface";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  useAddDocumentTypeVersion,
  useDocumentType,
} from "@/hooks/document-type-queries";
import { useTabParam } from "@/hooks/use-tab-param";
import { ApiError } from "@/lib/api";
import { plural, relativeTime } from "@/lib/format";
import type {
  DocumentType,
  DocumentTypeVersion,
} from "@/lib/types/document-types";

const TABS = ["fields", "samples", "tests"] as const;

export default function DocumentTypePage() {
  const { id } = useParams<{ id: string }>();
  const query = useDocumentType(id);
  if (query.isPending)
    return (
      <PageLayout icon={FileText} title="Document type" backHref="/document-types">
        <PageSkeleton statCards={0} viewTabs={3} showToolbar={false} tableRows={7} />
      </PageLayout>
    );
  if (query.isError)
    return (
      <PageLayout
        icon={FileText}
        title="Document type"
        backHref="/document-types"
      >
        {query.error instanceof ApiError && query.error.status === 404 ? (
          <EmptyState
            icon={SearchX}
            title="Document type not found"
            description="It may belong to another team, or the link is wrong."
            action={{
              label: "Back to document types",
              href: "/document-types",
            }}
          />
        ) : (
          <QueryError
            what="this document type"
            onRetry={() => query.refetch()}
            retrying={query.isFetching}
            error={query.error}
          />
        )}
      </PageLayout>
    );
  return <DocumentTypeView type={query.data} />;
}

function DocumentTypeView({ type }: { type: DocumentType }) {
  const [tab, setTab] = useTabParam(TABS, "fields");
  const [picked, setPicked] = React.useState<number | null>(null);
  const [editing, setEditing] = React.useState(false);
  const addVersion = useAddDocumentTypeVersion();
  const latest = type.versions[0];
  const shown = type.versions.find((v) => v.version === picked) ?? latest;

  return (
    <PageLayout
      icon={FileText}
      title={type.name}
      description={type.description ?? `Owned by ${type.team}`}
      backHref="/document-types"
      tabs={
        <Tabs
          value={tab}
          onValueChange={(t) => setTab(t as (typeof TABS)[number])}
        >
          <TabsList>
            <TabsTrigger value="fields">Fields</TabsTrigger>
            <TabsTrigger value="samples" data-testid="samples-tab">
              Samples · {type.samples.length}
            </TabsTrigger>
            <TabsTrigger value="tests" data-testid="tests-tab">
              Tests
            </TabsTrigger>
          </TabsList>
        </Tabs>
      }
      actions={
        <Select
          value={String(shown.version)}
          onValueChange={(v) => setPicked(Number(v))}
        >
          <SelectTrigger
            aria-label="Version"
            className="min-w-40"
            data-testid="version-picker"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end">
            {type.versions.map((v) => (
              <SelectItem key={v.version} value={String(v.version)}>
                v{v.version}
                {v.version === latest.version ? " · newest" : ""}
                {v.note ? ` · ${v.note}` : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      }
    >
      {tab === "samples" ? (
        <SamplesPanel type={type} latest={latest} />
      ) : tab === "tests" ? (
        <TestsPanel type={type} version={shown} />
      ) : (
        <FieldsPanel
          type={type}
          version={shown}
          latest={latest}
          onNewVersion={() => setEditing(true)}
        />
      )}
      {type.canEdit && (
        <FieldEditorDialog
          open={editing}
          onOpenChange={setEditing}
          typeName={type.name}
          from={shown}
          nextVersion={latest.version + 1}
          saving={addVersion.isPending}
          onSave={async (input) => {
            const saved = await addVersion.mutateAsync({ id: type.id, input });
            toast.success(`Saved ${type.name} v${saved.version}`, {
              description: "Extractions that name no version read with it now.",
            });
            setPicked(saved.version);
            setEditing(false);
          }}
        />
      )}
    </PageLayout>
  );
}

/** The shown version's fields, read-only; a change is saved as a new version. */
function FieldsPanel({
  type,
  version,
  latest,
  onNewVersion,
}: {
  type: DocumentType;
  version: DocumentTypeVersion;
  latest: DocumentTypeVersion;
  onNewVersion: () => void;
}) {
  return (
    <Section
      flush
      title={
        <span className="flex items-center gap-2">
          Fields of v{version.version}
          {version.version === latest.version ? (
            <Badge variant="secondary">Newest</Badge>
          ) : (
            <Badge variant="outline">Earlier version</Badge>
          )}
        </span>
      }
      description={[
        version.many
          ? "Reads several records per document"
          : "Reads one record per document",
        version.reviewBelow == null
          ? "no review threshold"
          : `reads below ${version.reviewBelow} confidence go to review`,
        `saved by ${version.createdBy} ${relativeTime(version.createdAt)}`,
        version.note,
      ]
        .filter(Boolean)
        .join(" · ")}
      actions={
        type.canEdit && (
          <Button
            variant="outline"
            size="sm"
            onClick={onNewVersion}
            data-testid="new-version-button"
          >
            <Plus className="size-4" /> New version
          </Button>
        )
      }
    >
      <Table data-testid="fields-table">
        <TableHeader>
          <TableRow>
            <TableHead>Field</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Required</TableHead>
            <TableHead>Allowed values</TableHead>
            <TableHead>Review</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {version.fields.map((f) => (
            <TableRow key={f.key}>
              <TableCell>
                <div className="text-sm font-medium">{fieldLabel(f)}</div>
                <div className="font-mono text-xs text-muted-foreground">
                  {f.key}
                </div>
              </TableCell>
              <TableCell className="text-sm">
                {FIELD_TYPE_LABELS[f.type]}
              </TableCell>
              <TableCell className="text-sm">
                {f.required ? (
                  "Required"
                ) : (
                  <span className="text-muted-foreground">Optional</span>
                )}
              </TableCell>
              <TableCell className="text-sm">
                {f.options?.length ? (
                  f.options.join(", ")
                ) : (
                  <span className="text-muted-foreground">—</span>
                )}
              </TableCell>
              <TableCell className="text-sm">
                {f.alwaysReview ? (
                  "Always"
                ) : f.reviewBelow != null ? (
                  `Below ${f.reviewBelow}`
                ) : (
                  <span className="text-muted-foreground">
                    Document’s threshold
                  </span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="border-t px-4 py-3 text-xs text-muted-foreground">
        {plural(version.fields.length, "field")} ·{" "}
        {plural(type.versions.length, "version")} saved. Versions never change;
        a change saves the next one.
      </p>
    </Section>
  );
}
