'use client';

import * as React from 'react';
import { AlertCircle } from 'lucide-react';
import { toast } from 'sonner';

import { ConfirmActionDialog } from '@/components/shared/confirm-action-dialog';
import { CopyButton } from '@/components/shared/copy-button';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { QueryError } from '@/components/shared/query-states';
import { Section } from '@/components/shared/surface';
import { TagInput } from '@/components/shared/tag-input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useCanBuild, useMe } from '@/hooks/me-queries';
import { WidgetPreviewSheet } from './widget-preview';
import { useAgents } from '@/hooks/queries';
import { count, relativeTime } from '@/lib/format';
import { useSticky } from '@/hooks/use-sticky';
import { useCreateWidgetDeployment, useUpdateWidgetDeployment, useWidgetDeployments } from '@/hooks/widget-deployment-queries';
import type { WidgetDeployment } from '@/lib/types/widget-deployments';
import { KEY_VARIABLE, SESSION_PATH, snippetFor, STEPS_DOC } from '@/lib/widget-snippet';

import { WidgetMintKeysDialog } from './widget-mint-keys';

// A page origin as the browser sends it: scheme and host, a port when it has one, nothing after.
const ORIGIN = /^https?:\/\/[a-z0-9.-]+(:\d{1,5})?$/i;
// The agents an embed can serve: published ones, by name.
const PUBLISHED = { page: 1, pageSize: 100, filters: { availability: ['published'] } };

function CodeBlock({ text, testId }: { text: string; testId: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border bg-muted/40 p-3">
      <pre className="min-w-0 flex-1 overflow-x-auto whitespace-pre font-mono text-xs" data-testid={testId}>
        {text}
      </pre>
      <CopyButton text={text} size="sm" variant="outline" />
    </div>
  );
}

/** The mint-key flow with this embed's ids filled in (lib/widget-snippet.ts): the bank's server, then the page. */
function Snippet({ deployment, scriptUrl, id }: { deployment: WidgetDeployment; scriptUrl: string; id?: string }) {
  const tenant = useMe().data?.tenantId ?? '<your tenant id>';
  const { server, page } = snippetFor(scriptUrl, deployment.id, tenant);
  return (
    <div className="flex flex-col gap-3" id={id}>
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">1. Your server</span> asks for a 15-minute session for each signed-in person, with a mint key from
        Mint keys kept in its secrets as <code>{KEY_VARIABLE}</code>:
      </p>
      <CodeBlock text={server} testId="widget-snippet-server" />
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">2. The page</span>, before <code>&lt;/body&gt;</code>. It asks your server&apos;s <code>{SESSION_PATH}</code> for
        the session; no key goes in the page.
      </p>
      <CodeBlock text={page} testId="widget-snippet" />
      <a href={STEPS_DOC} target="_blank" rel="noreferrer" className="text-xs underline-offset-4 hover:underline" data-testid="widget-snippet-steps">
        All steps, page events and errors
      </a>
    </div>
  );
}

/**
 * Creates an embed and then shows its snippet. Without `agentId` (Deployments > New deployment > Chat widget) it first
 * asks which published agent to embed.
 */
export function EmbedDialog({ agentId, scriptUrl, open, onOpenChange }: { agentId?: string; scriptUrl: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const create = useCreateWidgetDeployment();
  const agents = useAgents(PUBLISHED, { enabled: open && !agentId });
  const [picked, setPicked] = React.useState('');
  const chosen = agentId ?? picked;
  const [name, setName] = React.useState('');
  const [origins, setOrigins] = React.useState<string[]>([]);
  const [errors, setErrors] = React.useState<{ agent?: string; name?: string; origins?: string; submit?: string }>({});
  const [made, setMade] = React.useState<WidgetDeployment>();

  React.useEffect(() => {
    if (open) return;
    setName('');
    setPicked('');
    setOrigins([]);
    setErrors({});
    setMade(undefined);
  }, [open]);

  const submit = async () => {
    const found = {
      agent: chosen ? undefined : 'Choose the agent to embed.',
      name: name.trim() ? undefined : 'Name it so the team can tell embeds apart.',
      origins: !origins.length
        ? 'Add the page origin, like https://intranet.bank.example.'
        : origins.some((o) => !ORIGIN.test(o))
          ? `Use the page's origin: https:// and the host, a port if it has one, no path. Fix ${origins.filter((o) => !ORIGIN.test(o)).join(', ')}.`
          : undefined,
    };
    setErrors(found);
    if (found.agent || found.name || found.origins) return;
    try {
      setMade(await create.mutateAsync({ name: name.trim(), agentId: chosen, origins }));
      toast.success(`Embed ${name.trim()} is ready`);
    } catch (e) {
      setErrors({ submit: (e as Error).message });
    }
  };

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title={made ? `Embed ${made.name}` : 'Embed on a page'}
      description={made ? `Serves version ${made.agentVersion} until you move it to a newer one.` : 'Chat with this agent from your intranet. It serves the published version as of now.'}
      onSubmit={made ? undefined : submit}
      footer={
        made ? (
          <Button type="button" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        ) : (
          <>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <LoadingButton type="submit" isLoading={create.isPending} loadingText="Creating…" data-testid="widget-embed-create">
              Create embed
            </LoadingButton>
          </>
        )
      }
    >
      {made ? (
        <Snippet deployment={made} scriptUrl={scriptUrl} />
      ) : (
        <div className="flex flex-col gap-4">
          {!agentId && (
            <FormField id="widget-agent" label="Agent" error={errors.agent} hint="Only published agents can be embedded; each embed serves the version live now.">
              <Select value={picked} onValueChange={(v) => (setPicked(v), setErrors({}))}>
                <SelectTrigger id="widget-agent" className="w-full" aria-invalid={!!errors.agent} data-testid="widget-embed-agent">
                  <SelectValue placeholder={agents.isPending ? 'Loading agents…' : 'Choose an agent'} />
                </SelectTrigger>
                <SelectContent>
                  {(agents.data?.data ?? []).map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          )}
          <FormField id="widget-name" label="Name" error={errors.name}>
            <Input id="widget-name" value={name} aria-invalid={!!errors.name} onChange={(e) => (setName(e.target.value), setErrors({}))} placeholder="e.g. Intranet help" />
          </FormField>
          <FormField id="widget-origins" label="Pages allowed to embed it" error={errors.origins} hint="The page's origin as the browser sends it, like https://intranet.bank.example or https://intranet.bank.example:8443. Press Enter after each.">
            <TagInput id="widget-origins" value={origins} onChange={(v) => (setOrigins(v), setErrors({}))} placeholder="e.g. https://intranet.bank.example" validate={(o) => (ORIGIN.test(o) ? undefined : `${o} is not an origin: use https:// and the host, a port if it has one, no path.`)} invalid={!!errors.origins} />
          </FormField>
          {errors.submit && (
            <Alert variant="destructive">
              <AlertCircle />
              <AlertDescription>{errors.submit}</AlertDescription>
            </Alert>
          )}
        </div>
      )}
    </DialogShell>
  );
}

type EmbedChange = 'pause' | 'resume' | 'serve' | 'retire';

/** What each table action does to the pages that load the embed, said before it runs. */
function confirmText(d: WidgetDeployment, change: EmbedChange, latest: number | null) {
  const pages = d.origins.join(', ');
  if (change === 'pause') return { title: `Pause ${d.name}`, consequence: `The chat on ${pages} stops answering and shows an offline message until you resume it.`, confirmLabel: 'Pause', done: `${d.name} is paused`, patch: { paused: true } };
  if (change === 'retire')
    return {
      title: `Retire ${d.name}`,
      consequence: `The chat on ${pages} stops for good: open conversations end and no new ones start. ${d.name} stays listed here, and it cannot be resumed or changed.`,
      confirmLabel: 'Retire',
      done: `${d.name} is retired`,
      patch: { retired: true },
    };
  if (change === 'resume') return { title: `Resume ${d.name}`, consequence: `The chat on ${pages} answers again from version ${d.agentVersion}.`, confirmLabel: 'Resume', done: `${d.name} answers again`, patch: { paused: false } };
  return { title: `Serve version ${latest} on ${d.name}`, consequence: `The chat on ${pages} answers from version ${latest} instead of version ${d.agentVersion}.`, confirmLabel: `Serve v${latest}`, done: `${d.name} now serves version ${latest}`, patch: { serves: { kind: 'agent' as const, id: d.agentId, version: latest ?? d.agentVersion } } };
}

/**
 * The agent's chat on other sites (agents-service `/v1/widget-deployments`, c-117/c-118): each embed pins a published
 * version and lists the origins allowed to load it. Builders and admins of the agent's team create, pause and move
 * embeds; the snippet carries only the deployment id. `scriptUrl` comes from `useWidgetScriptUrl` in the page.
 */
export function WidgetEmbeds({
  agentId,
  publishedVersion,
  scriptUrl,
  createOpen,
  onCreateOpenChange,
  canEdit,
}: {
  agentId: string;
  publishedVersion?: number | null;
  scriptUrl: string;
  /** Lets the page's header open the embed dialog (c-130); the section keeps its own state otherwise. */
  createOpen?: boolean;
  onCreateOpenChange?: (open: boolean) => void;
  /** The agent's own flag (its detail response asks the route's check); the team's permission until it loads. */
  canEdit?: boolean;
}) {
  const list = useWidgetDeployments(agentId);
  const update = useUpdateWidgetDeployment();
  const teamCanBuild = useCanBuild();
  const canBuild = canEdit ?? teamCanBuild;
  const [ownOpen, setOwnOpen] = React.useState(false);
  const open = createOpen ?? ownOpen;
  const setOpen = onCreateOpenChange ?? setOwnOpen;
  const [shown, setShown] = React.useState<string>();
  const [keysFor, setKeysFor] = React.useState<WidgetDeployment>();
  const [previewing, setPreviewing] = React.useState<WidgetDeployment>();
  const me = useMe().data;
  const [asking, setAsking] = React.useState<{ deployment: WidgetDeployment; change: EmbedChange }>();
  // Kept after the dialog closes so its text does not blank while it fades out.
  const confirming = useSticky(asking);
  const ask = confirming ? confirmText(confirming.deployment, confirming.change, publishedVersion ?? null) : undefined;

  return (
    <Section
      title="Embeds on other sites"
      description="A chat window on your intranet or another site, signed in with the person's SSO. Usage counts conversations started in the last 7 days."
      actions={
        canBuild ? (
          <Button size="sm" onClick={() => setOpen(true)} data-testid="widget-embed-open">
            Embed on a page
          </Button>
        ) : undefined
      }
      flush
    >
      {list.isPending ? (
        <Skeleton className="m-4 h-16" />
      ) : list.isError ? (
        <QueryError what="embeds" onRetry={() => list.refetch()} retrying={list.isFetching} />
      ) : !list.data.length ? (
        <p className="p-4 text-sm text-muted-foreground">No embeds yet.</p>
      ) : (
        <Table data-testid="widget-embeds">
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Sites</TableHead>
              <TableHead>Keys</TableHead>
              <TableHead>Usage · 7d</TableHead>
              <TableHead>Version</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.data.map((d) => (
              <React.Fragment key={d.id}>
                <TableRow data-testid="widget-embed-row" data-id={d.id}>
                  <TableCell className="font-medium">
                    {d.name} {d.retiredAt ? <Badge variant="outline">Retired</Badge> : d.paused ? <Badge variant="secondary">Paused</Badge> : null}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">{d.origins.join(', ')}</TableCell>
                  <TableCell className="tabular-nums" data-testid="widget-embed-keys">
                    {d.activeKeys ?? 0}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs" data-testid="widget-embed-usage">
                    <span className="tabular-nums">{count(d.conversations7d ?? 0)}</span> conversation{d.conversations7d === 1 ? '' : 's'}
                    <span className="block text-muted-foreground">{d.retiredAt ? `Retired ${relativeTime(d.retiredAt)}` : d.lastUsedAt ? `Last used ${relativeTime(d.lastUsedAt)}` : 'Not used yet'}</span>
                  </TableCell>
                  <TableCell>v{d.agentVersion}</TableCell>
                  <TableCell className="space-x-2 text-right">
                    {d.retiredAt ? null : (
                      <>
                    <Button size="sm" variant="ghost" aria-expanded={shown === d.id} aria-controls={`widget-snippet-${d.id}`} onClick={() => setShown(shown === d.id ? undefined : d.id)}>
                      {shown === d.id ? 'Hide snippet' : 'Snippet'}
                    </Button>
                    {canBuild && publishedVersion && publishedVersion > d.agentVersion ? (
                      <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => setAsking({ deployment: d, change: 'serve' })}>
                        Serve v{publishedVersion}
                      </Button>
                    ) : null}
                    {canBuild && !d.paused ? (
                      <Button size="sm" variant="outline" onClick={() => setPreviewing(d)} data-testid="widget-preview-open">
                        Preview
                      </Button>
                    ) : null}
                    {canBuild ? (
                      <Button size="sm" variant="outline" onClick={() => setKeysFor(d)} data-testid="widget-keys-open">
                        Mint keys
                      </Button>
                    ) : null}
                    {canBuild ? (
                      <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => setAsking({ deployment: d, change: d.paused ? 'resume' : 'pause' })}>
                        {d.paused ? 'Resume' : 'Pause'}
                      </Button>
                    ) : null}
                    {canBuild ? (
                      <Button size="sm" variant="ghost" className="text-destructive" disabled={update.isPending} onClick={() => setAsking({ deployment: d, change: 'retire' })} data-testid="widget-retire">
                        Retire
                      </Button>
                    ) : null}
                      </>
                    )}
                  </TableCell>
                </TableRow>
                {shown === d.id ? (
                  <TableRow>
                    <TableCell colSpan={6}>
                      <Snippet deployment={d} scriptUrl={scriptUrl} id={`widget-snippet-${d.id}`} />
                    </TableCell>
                  </TableRow>
                ) : null}
              </React.Fragment>
            ))}
          </TableBody>
        </Table>
      )}
      <EmbedDialog agentId={agentId} scriptUrl={scriptUrl} open={open} onOpenChange={setOpen} />
      {previewing ? <WidgetPreviewSheet deployment={previewing} tenant={me?.tenantId ?? ''} me={me?.user.name ?? 'you'} open={!!previewing} onOpenChange={(o) => !o && setPreviewing(undefined)} /> : null}
      {keysFor ? <WidgetMintKeysDialog deployment={keysFor} open={!!keysFor} onOpenChange={(o) => !o && setKeysFor(undefined)} /> : null}
      {ask && confirming ? (
        <ConfirmActionDialog
          open={!!asking}
          onOpenChange={(o) => !o && setAsking(undefined)}
          title={ask.title}
          consequence={ask.consequence}
          runsNow
          note={confirming.change === 'retire' ? 'Takes effect now and cannot be undone.' : 'Takes effect now. You can change it back from this table.'}
          confirmLabel={ask.confirmLabel}
          destructive={confirming.change === 'retire'}
          isPending={update.isPending}
          onConfirm={async () => {
            const out = await update.mutateAsync({ id: confirming.deployment.id, patch: ask.patch });
            // A serves or origins change waits for the team's publish review when it has one.
            if (out?.reviewId) toast.success('Sent for review', { description: 'It takes effect once someone approves it in Human Tasks.' });
            else toast.success(ask.done);
          }}
        />
      ) : null}
    </Section>
  );
}
