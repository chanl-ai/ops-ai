'use client';

/**
 * Start from a template: the templates of one kind that the team's packs and apps offer, from every source, each added
 * to the team as its own copy through the kind's create checks. One component for every list page that makes things a
 * team can start from (skills, agents, guardrails, document types, workflows); an app's Resources tab shows the same
 * templates per app.
 */
import * as React from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { LayoutTemplate, Search } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { DialogShell } from '@/components/shared/dialog-shell';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Row, Rows } from '@/components/shared/surface';
import { useTeamQuery } from '@/hooks/team-query';
import { ApiError } from '@/lib/api/contract';
import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';

type Raw = OpsAI['raw'];
export type Template = Awaited<ReturnType<Raw['agents']['templates_list_templates']>>[number];
export type TemplateKind = 'agent' | 'skill' | 'workflow' | 'guardrail' | 'document_type';

const NOUN: Record<TemplateKind, string> = {
  agent: 'agent',
  skill: 'skill',
  workflow: 'workflow',
  guardrail: 'guardrail',
  document_type: 'document type',
};

const refOf = (t: { source: string; id: string }) => `${t.source}:${t.id}`;

// Document types are kept by documents-service; every other kind by agents-service.
const listOf = (kind: TemplateKind) =>
  kind === 'document_type'
    ? (sdk((ops) => ops.raw.documents.templates_list_templates({ query: { kind } })) as unknown as Promise<Template[]>)
    : sdk((ops) => ops.raw.agents.templates_list_templates({ query: { kind } }));

export const useTemplates = (kind: TemplateKind, enabled = true) =>
  useTeamQuery({ queryKey: ['templates', 'kind', kind], queryFn: () => listOf(kind), enabled });

export function useInstallTemplate(kind: TemplateKind) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (t: Template): Promise<{ copy?: { recordId?: string } }> => {
      const path = { resource: refOf(t) };
      return kind === 'document_type'
        ? sdk((ops) => ops.raw.documents.resources_copy_resource({ path, body: {} }))
        : sdk((ops) => ops.raw.agents.resources_copy_resource({ path, body: {} }));
    },
    onSettled: () => qc.invalidateQueries(),
  });
}

/** The page's "From a template" button and its gallery dialog. `href` is the page a copy opens on. */
export function TemplatesGallery({ kind, href }: { kind: TemplateKind; href: string }) {
  const [open, setOpen] = React.useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)} data-testid="templates-gallery-button">
        <LayoutTemplate className="size-4" /> From a template
      </Button>
      <TemplatesDialog kind={kind} href={href} open={open} onOpenChange={setOpen} />
    </>
  );
}

function TemplatesDialog({
  kind,
  href,
  open,
  onOpenChange,
}: {
  kind: TemplateKind;
  href: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const query = useTemplates(kind, open);
  const install = useInstallTemplate(kind);
  const [search, setSearch] = React.useState('');
  const [adding, setAdding] = React.useState<string | null>(null);
  const noun = NOUN[kind];
  const rows = React.useMemo(() => {
    const q = search.trim().toLowerCase();
    const all = query.data ?? [];
    return q ? all.filter((t) => `${t.title} ${t.plugin.title}`.toLowerCase().includes(q)) : all;
  }, [query.data, search]);

  const add = async (t: Template) => {
    setAdding(refOf(t));
    try {
      const made = await install.mutateAsync(t);
      toast.success(`${t.title} added to your team as a draft ${noun}.`);
      onOpenChange(false);
      if (made.copy?.recordId) router.push(`${href}/${made.copy.recordId}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : `Could not add ${t.title}.`);
    } finally {
      setAdding(null);
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title={`Start a ${noun} from a template`}
      description={`Templates from the packs and apps your team has on. Adding one makes your team's own copy, which you can edit.`}
    >
      <div className="relative mb-3">
        <Search className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search templates"
          aria-label="Search templates"
          className="pl-8"
        />
      </div>
      {query.isPending ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : query.isError ? (
        <QueryError what="templates" error={query.error} onRetry={() => query.refetch()} retrying={query.isFetching} />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-6 text-center text-sm" data-testid="templates-gallery-empty">
          {search
            ? 'No template matches this search.'
            : `No ${noun} templates yet. A team admin turns on a pack or app on the Apps page to offer some.`}
        </p>
      ) : (
        <Rows testId="templates-gallery">
          {rows.map((t) => (
            <Row
              key={refOf(t)}
              title={t.title}
              description={t.plugin.title}
              trailing={
                t.copy?.recordId ? (
                  <Button variant="outline" size="sm" onClick={() => router.push(`${href}/${t.copy!.recordId}`)}>
                    Open your copy
                  </Button>
                ) : t.canAdd ? (
                  <LoadingButton
                    size="sm"
                    isLoading={adding === refOf(t)}
                    disabled={adding !== null}
                    onClick={() => add(t)}
                    data-testid={`templates-gallery-add-${t.id}`}
                  >
                    Add to team
                  </LoadingButton>
                ) : (
                  <Badge variant="outline">Ask an admin to add it</Badge>
                )
              }
            />
          ))}
        </Rows>
      )}
    </DialogShell>
  );
}
