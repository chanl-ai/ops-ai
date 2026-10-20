'use client';

import * as React from 'react';
import { useParams } from 'next/navigation';
import { AlertCircle, LayoutTemplate } from 'lucide-react';
import { toast } from 'sonner';

import { LayoutWidget } from '@/components/chat/widget-layout';
import { PageLayout } from '@/components/page-layout';
import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { EmptyState } from '@/components/shared/empty-state';
import { FormField } from '@/components/shared/form-field';
import { BuilderFieldset, ReadOnlyNotice } from '@/components/shared/builder-only';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { RecordSkeleton } from '@/components/shared/record-skeleton';
import { SettingsSection } from '@/components/shared/settings-section';
import { SplitView } from '@/components/shared/setting/split-view';
import { Section } from '@/components/shared/surface';
import { announcePublish } from '@/components/shared/publish-result';
import { fieldDrafts, type FieldDraft, InputSchemaEditor, schemaOf } from '@/components/tools/input-schema-editor';
import { LayoutEditor } from '@/components/widgets/layout-editor';
import { SampleEditor } from '@/components/widgets/sample-editor';
import { WidgetStatusBadge } from '@/components/widgets/widget-status-badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useCanBuild } from '@/hooks/me-queries';
import { useRequestWidgetPublish, useRetireWidget, useUpdateWidget, useWidgetTemplate } from '@/hooks/widget-queries';
import { ApiError } from '@/lib/api/contract';
import type { TemplateNode, WidgetTemplate } from '@/lib/types/widgets';
import { fillTemplate } from '@/lib/widgets/bind';
import { rowsOfSchema, schemaOfRows } from '@/lib/widgets/schema-fields';

// The building blocks a widget is laid out from: the catalogue the kernel accepts (ops_agent_kernel.layout).
const CATALOGUE: [string, string][] = [
  ['card', 'title, children'],
  ['row, column', 'children, gap (sm, md, lg), align'],
  ['title, text, caption', 'text'],
  ['badge', 'text, tone (neutral, info, success, warning, danger), tones: value to tone'],
  ['metric', 'label, value, unit, delta'],
  ['table', 'rows, columns: [{ key, label, format }]'],
  ['chart', 'rows, x, y: [keys], kind (line, bar, area)'],
  ['keyValue', 'items: [{ label, value }]'],
  ['list', 'items'],
  ['button', 'label, reply: { text, values } (sent back to the agent as the next message)'],
  ['divider', 'nothing'],
];

const pretty = (v: unknown) => JSON.stringify(v ?? {}, null, 2);

function parsed(text: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(text) };
  } catch (e) {
    return { error: (e as Error).message };
  }
}

function Editor({ widget }: { widget: WidgetTemplate }) {
  const update = useUpdateWidget();
  const teamCanBuild = useCanBuild('widgets');
  // The widget's own flag (the detail response asks the routes' checks); the team's permission until it loads.
  const canBuild = widget.canEdit ?? teamCanBuild;
  const publish = useRequestWidgetPublish();
  const [name, setName] = React.useState(widget.name);
  const [useWhen, setUseWhen] = React.useState(widget.useWhen);
  // The form edits objects; the JSON view edits text and is parsed back when the builder returns to the form.
  const start = rowsOfSchema(widget.dataSchema);
  const [mode, setMode] = React.useState<'form' | 'json'>(start.editable ? 'form' : 'json');
  const [tree, setTree] = React.useState<TemplateNode>(widget.tree);
  const [drafts, setDrafts] = React.useState<FieldDraft[]>(fieldDrafts(start.fields));
  const [kept, setKept] = React.useState({ extras: start.extras, rest: start.rest, editable: start.editable });
  const [sample, setSample] = React.useState<Record<string, unknown>>(widget.sample ?? {});
  const [text, setText] = React.useState({ tree: pretty(widget.tree), schema: pretty(widget.dataSchema), sample: pretty(widget.sample) });
  const [modeError, setModeError] = React.useState<string>();
  const [saveError, setSaveError] = React.useState<string>();
  const retire = useRetireWidget();
  const [retiring, setRetiring] = React.useState(false);
  const [reason, setReason] = React.useState('');
  const retired = widget.status === 'deprecated';

  const formSchema = schemaOfRows(schemaOf(drafts), kept.extras, kept.rest);
  const t = mode === 'json' ? parsed(text.tree) : { value: tree };
  const s = mode === 'json' ? parsed(text.schema) : { value: formSchema };
  const d = mode === 'json' ? parsed(text.sample) : { value: sample };
  const preview = !t.error && !d.error && t.value ? fillTemplate(t.value as TemplateNode, d.value) : null;
  const current = JSON.stringify([name, useWhen, t.value, s.value, d.value]);
  const dirty = !(t.error || s.error || d.error) ? current !== JSON.stringify([widget.name, widget.useWhen, widget.tree, widget.dataSchema, widget.sample ?? {}]) : true;
  const invalid = !!(t.error || s.error || d.error);
  const names = drafts.map((f) => f.name.trim()).filter(Boolean);
  const fields = { all: names, lists: drafts.filter((f) => f.type === 'array' && f.name.trim()).map((f) => f.name.trim()) };

  const switchMode = (next: 'form' | 'json') => {
    setModeError(undefined);
    if (next === mode) return;
    if (next === 'json') return (setText({ tree: pretty(tree), schema: pretty(formSchema), sample: pretty(sample) }), setMode('json'));
    if (invalid) return setModeError('Fix the JSON before going back to the form.');
    const rows = rowsOfSchema(s.value as Record<string, unknown>);
    if (!rows.editable) return setModeError('This schema uses JSON Schema features the form does not edit; keep editing it here.');
    setTree(t.value as TemplateNode);
    setDrafts(fieldDrafts(rows.fields));
    setKept({ extras: rows.extras, rest: rows.rest, editable: true });
    setSample((d.value ?? {}) as Record<string, unknown>);
    setMode('form');
  };

  const save = async () => {
    setSaveError(undefined);
    try {
      const w = await update.mutateAsync({ widgetId: widget.widgetId, input: { name: name.trim(), useWhen: useWhen.trim(), tree: t.value as TemplateNode, dataSchema: s.value as Record<string, unknown>, sample: (d.value ?? {}) as Record<string, unknown> } });
      toast.success(`Saved ${w.name} v${w.version} as a draft`, { description: 'Publish it to let agents pin this version.' });
    } catch (e) {
      setSaveError((e as Error).message);
    }
  };
  const requestPublish = async () => {
    try {
      const w = await publish.mutateAsync({ widgetId: widget.widgetId, version: widget.version });
      announcePublish({ name: w.name, version: w.version, live: w.status === 'published', liveNote: 'Agents can pin it now.', decidedBy: 'A reviewer in the owning team' });
    } catch (e) {
      toast.error(`Couldn’t publish ${widget.name}`, { description: (e as Error).message });
    }
  };

  return (
    <PageLayout
      icon={LayoutTemplate}
      title={widget.name}
      description={widget.useWhen}
      backHref="/widgets"
      badge={<WidgetStatusBadge widget={widget} />}
      actions={
        canBuild && (
        <div className="flex gap-2">
          {!retired && widget.canDelete !== false && (
            <Button variant="ghost" className="text-destructive" onClick={() => (setReason(''), setRetiring(true))} data-testid="retire-widget">
              Retire
            </Button>
          )}
          <LoadingButton variant="outline" isLoading={publish.isPending} loadingText="Sending…" disabled={dirty || retired || (widget.status ?? 'published') === 'published'} onClick={requestPublish} data-testid="publish-widget">
            Publish
          </LoadingButton>
          <LoadingButton isLoading={update.isPending} loadingText="Saving…" disabled={!dirty || invalid || retired} onClick={save} data-testid="save-widget">
            Save draft
          </LoadingButton>
        </div>
        )
      }
    >
      <ConfirmActionDialog
        open={retiring}
        onOpenChange={setRetiring}
        title={`Retire ${widget.name}?`}
        consequence="Agents can no longer pin it. Agents that already pin it keep showing the version they pinned."
        runsNow
        note="This cannot be undone."
        confirmLabel="Retire widget"
        destructive
        confirmDisabled={!reason.trim()}
        isPending={retire.isPending}
        onConfirm={async () => {
          await retire.mutateAsync({ widgetId: widget.widgetId, reason: reason.trim() });
          toast.success(`Retired ${widget.name}`, { description: 'It takes no new pins.' });
        }}
      >
        <FormField id="retire-reason" label="Why">
          <Textarea id="retire-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Replaced by Case summary v2" />
        </FormField>
      </ConfirmActionDialog>
      <SplitView
        id="widget-definition"
        bare
        left={
        <div className="flex min-w-0 flex-col gap-4">
          <ReadOnlyNotice noun="widgets" area="widgets" canEdit={widget.canEdit} />
          <BuilderFieldset area="widgets" canEdit={widget.canEdit}>
          {saveError && (
            <Alert variant="destructive" data-testid="widget-save-error">
              <AlertCircle />
              <AlertDescription>{saveError}</AlertDescription>
            </Alert>
          )}
          <SettingsSection title="Identity" description="The name builders see, and the line the agent reads to decide when to use it.">
            <div className="flex flex-col gap-4">
              <FormField id="widget-name" label="Name">
                <Input id="widget-name" value={name} onChange={(e) => setName(e.target.value)} />
              </FormField>
              <FormField id="widget-use-when" label="When the agent uses it">
                <Textarea id="widget-use-when" rows={2} value={useWhen} onChange={(e) => setUseWhen(e.target.value)} />
              </FormField>
            </div>
          </SettingsSection>
          <div className="flex flex-wrap items-center gap-3">
            <ToggleGroup type="single" variant="outline" size="sm" value={mode} onValueChange={(v) => v && switchMode(v as 'form' | 'json')} aria-label="Editor">
              <ToggleGroupItem value="form" disabled={!kept.editable && mode === 'json' && invalid} data-testid="widget-mode-form">
                Form
              </ToggleGroupItem>
              <ToggleGroupItem value="json" data-testid="widget-mode-json">
                JSON (advanced)
              </ToggleGroupItem>
            </ToggleGroup>
            {modeError && (
              <p className="text-sm text-destructive" role="alert">
                {modeError}
              </p>
            )}
          </div>
          {mode === 'form' ? (
            <>
              <SettingsSection title="Data" description="The fields the agent fills, and sample values for the preview. Limits set in JSON, such as a maximum length, are kept.">
                <div className="flex flex-col gap-6">
                  <InputSchemaEditor value={drafts} onChange={setDrafts} note="A required field must be in every answer that shows this widget. Add a field of type array for a table, chart or list." />
                  <SampleEditor fields={schemaOf(drafts)} value={sample} onChange={setSample} />
                </div>
              </SettingsSection>
              <SettingsSection title="Layout" description="Blocks from the catalogue. Each value is fixed or taken from a data field.">
                <LayoutEditor tree={tree} onChange={setTree} fields={fields} />
              </SettingsSection>
            </>
          ) : (
            <>
              <SettingsSection title="Layout" description='Building blocks from the catalogue. A field holds a value, or { "$bind": "/field" } to take it from the data.'>
                <FormField id="widget-tree" label="Layout" error={t.error}>
                  <Textarea id="widget-tree" rows={16} className="font-mono text-xs" value={text.tree} onChange={(e) => setText({ ...text, tree: e.target.value })} spellCheck={false} />
                </FormField>
              </SettingsSection>
              <SettingsSection title="Data" description="The fields the agent must supply, as JSON Schema, and sample data for the preview.">
                <div className="flex flex-col gap-4">
                  <FormField id="widget-schema" label="Data schema" error={s.error}>
                    <Textarea id="widget-schema" rows={10} className="font-mono text-xs" value={text.schema} onChange={(e) => setText({ ...text, schema: e.target.value })} spellCheck={false} />
                  </FormField>
                  <FormField id="widget-sample" label="Sample data" error={d.error}>
                    <Textarea id="widget-sample" rows={8} className="font-mono text-xs" value={text.sample} onChange={(e) => setText({ ...text, sample: e.target.value })} spellCheck={false} />
                  </FormField>
                </div>
              </SettingsSection>
            </>
          )}
        </BuilderFieldset>
        </div>
        }
        right={
        <div className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-4 lg:self-start">
          <Section title="Preview" description="Drawn by the same renderer as chat, filled with the sample data.">
            <div data-testid="widget-preview">
              {preview ? (
                <LayoutWidget part={{ type: 'widget', id: 'preview', layout: preview, template: { id: widget.widgetId, version: widget.version, name } }} />
              ) : (
                <EmptyState icon={LayoutTemplate} title="Nothing to preview" description={t.error || d.error ? 'Fix the JSON on the left to see the widget.' : 'The sample data leaves every block empty. Give the fields sample values.'} />
              )}
            </div>
          </Section>
          <Section title="Building blocks" description="Only these can appear in a widget; anything else is refused on save.">
            <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
              {CATALOGUE.map(([k, v]) => (
                <React.Fragment key={k}>
                  <dt className="font-mono text-xs">{k}</dt>
                  <dd className="text-xs text-muted-foreground">{v}</dd>
                </React.Fragment>
              ))}
            </dl>
          </Section>
        </div>
        }
      />
    </PageLayout>
  );
}

export default function WidgetPage() {
  const { id } = useParams<{ id: string }>();
  const query = useWidgetTemplate(id);
  const widget = query.data;
  if (query.isPending) return <RecordSkeleton railSide="right" />;
  const missing = query.error instanceof ApiError && query.error.status === 404;
  if (query.isError && !query.data && !missing) return <QueryError what="widget" onRetry={() => query.refetch()} retrying={query.isFetching} error={query.error} />;
  if (!widget) return <EmptyState icon={LayoutTemplate} title="Widget not found" description="It may have been removed, or the link is wrong." action={{ label: 'Back to widgets', href: '/widgets' }} />;
  // Keyed by version and status, so the editor reloads its fields after a save or a publish.
  return <Editor key={`${widget.widgetId}-${widget.version}-${widget.status}`} widget={widget} />;
}
