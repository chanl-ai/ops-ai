'use client';

/**
 * Start from a template: the templates of one kind that the team's packs and apps offer, from every source, each added
 * to the team as its own copy through the kind's create checks. One component for every list page that makes things a
 * team can start from (skills, agents, guardrails, document types, workflows); an app's Resources tab shows the same
 * templates per app.
 */
import * as React from 'react';
import Link from 'next/link';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { LayoutTemplate } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { SearchAddDialog } from '@/components/shared/search-add-dialog';
import { packFor } from '@/lib/template-packs';
import { type ServerListAsk, useServerList } from '@/hooks/server-list';
import { ApiError } from '@/lib/api/contract';
import { sdk } from '@/lib/api/ops-sdk';
import type { OpsAI } from '@chanl-ai/ops-ai';

type Raw = OpsAI['raw'];
type TemplatePage = Awaited<ReturnType<Raw['agents']['templates_list_templates']>>;
export type Template = TemplatePage['data'][number];
export type TemplateKind = 'agent' | 'skill' | 'workflow' | 'guardrail' | 'document_type';

const NOUN: Record<TemplateKind, string> = {
  agent: 'agent',
  skill: 'skill',
  workflow: 'workflow',
  guardrail: 'guardrail',
  document_type: 'document type',
};

const refOf = (t: { source: string; id: string }) => `${t.source}:${t.id}`;

// Document types are kept by documents-service; every other kind by agents-service. Both answer a page of the shared list.
const pageOf = (kind: TemplateKind, ask: ServerListAsk) =>
  kind === 'document_type'
    ? (sdk((ops) => ops.raw.documents.templates_list_templates({ query: { kind, ...ask } })) as unknown as Promise<TemplatePage>)
    : sdk((ops) => ops.raw.agents.templates_list_templates({ query: { kind, ...ask } }));

/** The templates of one kind matching `search`, searched and paged by the service. */
export const useTemplates = (kind: TemplateKind, search: string, enabled = true) =>
  useServerList(['templates', 'kind', kind], (ask) => pageOf(kind, ask), { search, enabled });

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
  const [search, setSearch] = React.useState('');
  const query = useTemplates(kind, search, open);
  const install = useInstallTemplate(kind);
  const pack = packFor(kind);
  const noun = NOUN[kind];

  const add = async (t: Template) => {
    try {
      const made = await install.mutateAsync(t);
      toast.success(`${t.title} added to your team as a draft ${noun}.`);
      onOpenChange(false);
      if (made.copy?.recordId) router.push(`${href}/${made.copy.recordId}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : `Could not add ${t.title}.`);
    }
  };

  return (
    <SearchAddDialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Start a ${noun} from a template`}
      description="Templates from the packs and apps your team has on. Adding one makes your team's own copy, which you can edit."
      searchLabel="Search templates"
      what="templates"
      search={search}
      onSearchChange={setSearch}
      query={query}
      empty={
        pack ? (
          <>
            {`No ${noun} templates yet. A team admin turns on the `}
            <Link href={pack.href} className="text-primary underline-offset-4 hover:underline" data-testid="templates-gallery-pack">
              {pack.name}
            </Link>
            {' pack to offer some.'}
          </>
        ) : (
          <>
            {`No ${noun} templates yet. A team admin turns on an app on `}
            <Link href="/data/connectors" className="text-primary underline-offset-4 hover:underline" data-testid="templates-gallery-connectors">
              Connectors
            </Link>
            {' to offer some.'}
          </>
        )
      }
      rowKey={refOf}
      rowTitle={(t) => t.title}
      rowDescription={(t) => t.plugin.title}
      preview={(t) => <TemplatePreview template={t} href={href} />}
      addLabel={`Add to team`}
      canAdd={(t) => t.canAdd && !t.copy?.recordId}
      onAdd={add}
      testId="templates-gallery"
    />
  );
}

/** What the chosen template brings and needs, as the service reports it; an existing copy opens instead of adding. */
function TemplatePreview({ template: t, href }: { template: Template; href: string }) {
  const router = useRouter();
  const needs = [...t.requires.tools.map((x) => `Tool: ${x}`), ...t.requires.resources.map((x) => `Resource: ${x}`)];
  return (
    <div className="flex flex-col gap-3" data-testid="templates-gallery-preview-body">
      <div>
        <h3 className="text-sm font-semibold">{t.title}</h3>
        <p className="text-xs text-muted-foreground">
          {t.plugin.title} · version {t.version}
        </p>
      </div>
      <div>
        <h4 className="mb-1 text-xs font-medium text-muted-foreground">Needs</h4>
        {needs.length ? (
          <div className="flex flex-wrap gap-1">
            {needs.map((n) => (
              <Badge key={n} variant="outline">
                {n}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-sm">Nothing else. It works as soon as it is added.</p>
        )}
      </div>
      {t.copy?.recordId ? (
        <Button variant="outline" size="sm" className="self-start" onClick={() => router.push(`${href}/${t.copy!.recordId}`)}>
          Open your copy
        </Button>
      ) : !t.canAdd ? (
        <Badge variant="outline" className="self-start">
          Ask an admin to add it
        </Badge>
      ) : null}
    </div>
  );
}
