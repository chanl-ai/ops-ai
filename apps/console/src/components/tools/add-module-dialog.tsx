'use client';

import * as React from 'react';
import { AlertTriangle, Braces, Code2, Globe, Plug, Plus } from 'lucide-react';

import { DialogShell } from '@/components/shared/dialog-shell';
import { FileUpload, uploadsBlocker, uploadsReady } from '@/components/shared/file-upload';
import { FormField } from '@/components/shared/form-field';
import { LoadingButton } from '@/components/shared/loading-button';
import { Stepper } from '@/components/shared/stepper';
import { AccessBadge } from '@/components/status-badges';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { ConnectionRef } from '@/lib/types/integrations';
import { plural } from '@/lib/format';
import type { ToolAccess } from '@/lib/types/domain';
import type { DiscoveredOperation, DiscoveryResult, HttpOperationInput, ModuleInput, ModuleSource, ModuleType } from '@/lib/types/tool-modules';
import { cn } from '@/lib/utils';

import { HttpOperationBuilder, inputsOf } from './http-operation-builder';
import { ConnectionChip, IntegrationStatusBadge, SystemMark } from '@/components/integrations/integration-meta';
import { OperationPicker } from './operation-picker';

const STEPS = ['Source', 'Operations', 'Review'] as const;
type Kind = 'mcp' | 'openapi' | 'http' | 'code';

const KINDS: { kind: Kind; label: string; hint: string; icon: typeof Plug; disabled?: string }[] = [
  { kind: 'mcp', label: 'MCP server', hint: 'Connect a remote server; choose which of its tools to expose', icon: Plug },
  { kind: 'openapi', label: 'OpenAPI spec', hint: 'Import a spec by URL or file; pick the operations', icon: Braces },
  { kind: 'http', label: 'HTTP operation', hint: 'Build one request: method, URL, headers, body', icon: Globe },
  { kind: 'code', label: 'Code', hint: 'Functions run in a sandbox', icon: Code2, disabled: 'Needs the code sandbox, planned after the first workflow ships' },
];

const EMPTY_HTTP: HttpOperationInput = { name: '', description: '', access: 'read', method: 'GET', url: '', headers: [{ key: 'Accept', value: 'application/json' }], body: '' };
/** Null for a valid https URL; otherwise what is wrong with it. */
function httpsProblem(raw: string) {
  let u: URL;
  try {
    u = new URL(raw.trim());
  } catch {
    return 'That is not a complete address. Enter it with https://, e.g. https://servicenow.northfield.internal/mcp.';
  }
  if (u.protocol !== 'https:') return 'Use an https address; the gateway does not call plain http.';
  if (!u.hostname.includes('.')) return 'Enter the full host name, e.g. servicenow.northfield.internal.';
  return null;
}

const kebab = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/**
 * Add a module from an MCP server, an OpenAPI spec or one HTTP operation, calling through an existing connection
 * from Integrations (or one connected from here). Saves a draft and opens its page.
 */
export function AddModuleDialog({
  open,
  onOpenChange,
  connections,
  connectionsLoading,
  newConnectionId,
  onConnectNew,
  onDiscover,
  discovering,
  onCreate,
  creating,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  connections: ConnectionRef[];
  connectionsLoading: boolean;
  /** Set after "Connect a new system" finishes, so the new connection is picked. */
  newConnectionId?: string;
  onConnectNew: () => void;
  onDiscover: (source: ModuleSource) => Promise<DiscoveryResult>;
  discovering: boolean;
  onCreate: (input: ModuleInput) => Promise<void>;
  creating: boolean;
}) {
  const [step, setStep] = React.useState(1);
  const [kind, setKind] = React.useState<Kind>('mcp');
  const [url, setUrl] = React.useState('');
  const [specUrl, setSpecUrl] = React.useState('');
  const [fileName, setFileName] = React.useState('');
  const [specFileId, setSpecFileId] = React.useState('');
  const [specWaiting, setSpecWaiting] = React.useState<string | undefined>();
  const [connectionId, setConnectionId] = React.useState('');
  const [found, setFound] = React.useState<DiscoveryResult | null>(null);
  const [selected, setSelected] = React.useState<Map<string, ToolAccess>>(new Map());
  const [http, setHttp] = React.useState<HttpOperationInput>(EMPTY_HTTP);
  const [displayName, setDisplayName] = React.useState('');
  const [name, setName] = React.useState('');
  const [system, setSystem] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);
  /** Errors that belong to one field render under it, not in the banner. */
  const [fieldErr, setFieldErr] = React.useState<Partial<Record<'url' | 'spec' | 'display' | 'name' | 'connection', string>>>({});
  const [touched, setTouched] = React.useState(false);
  const bodyRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    if (!open) return;
    setStep(1);
    setKind('mcp');
    setUrl('');
    setSpecUrl('');
    setFileName('');
    setSpecFileId('');
    setSpecWaiting(undefined);
    setConnectionId('');
    setFound(null);
    setSelected(new Map());
    setHttp(EMPTY_HTTP);
    setDisplayName('');
    setName('');
    setSystem('');
    setError(null);
    setFieldErr({});
    setTouched(false);
  }, [open]);

  React.useEffect(() => {
    if (newConnectionId) setConnectionId(newConnectionId);
  }, [newConnectionId]);

  const usable = connections.filter((c) => c.status !== 'revoked');
  const connection = connections.find((c) => c.id === connectionId);

  React.useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [step]);

  const httpErrors = touched ? { name: /^[a-z][a-z0-9_]{2,}$/.test(http.name) ? undefined : 'Use lower case letters, digits and underscores.', url: /^https:\/\/[^\s]+$/.test(http.url) ? undefined : 'Enter the full https URL.' } : undefined;

  async function next() {
    setError(null);
    setFieldErr({});
    if (step === 1) {
      if (!connection) return setFieldErr({ connection: 'Choose the connection this module calls through, or connect a new system.' });
      if (kind === 'http') {
        setStep(2);
        return;
      }
      const source: ModuleSource | null =
        kind === 'mcp'
          ? url.trim()
            ? { kind: 'mcp', url: url.trim(), connectionId }
            : null
          : specUrl.trim() || specFileId
            ? { kind: 'openapi', specUrl: specUrl.trim() || undefined, fileName: specFileId ? fileName : undefined, fileId: specFileId || undefined, connectionId }
            : null;
      if (kind === 'openapi' && !specUrl.trim() && specWaiting) {
        setFieldErr({ spec: specWaiting });
        return;
      }
      if (!source) {
        setFieldErr(kind === 'mcp' ? { url: 'Enter the server’s address, e.g. https://servicenow.northfield.internal/mcp.' } : { spec: 'Add the spec as a URL or a file.' });
        return;
      }
      if (source.kind === 'mcp') {
        const problem = httpsProblem(source.url);
        if (problem) return setFieldErr({ url: problem });
      }
      if (source.kind === 'openapi' && source.specUrl) {
        const problem = httpsProblem(source.specUrl);
        if (problem) return setFieldErr({ spec: problem });
      }
      try {
        const d = await onDiscover(source);
        setFound(d);
        // Reads start selected; writes and money movement are opt-in so nothing that changes data is exposed by default.
        setSelected(new Map(d.operations.filter((o) => o.access === 'read').map((o) => [o.name, o.access])));
        setDisplayName(d.system);
        setName(d.suggestedName);
        setSystem(d.system);
        setStep(2);
      } catch (e) {
        // Discovery failures are about the address the user typed, so they sit on that field.
        const message = (e as Error).message;
        if (kind === 'mcp') setFieldErr({ url: message });
        else if (kind === 'openapi') setFieldErr({ spec: message });
        else setError(message);
      }
      return;
    }
    if (step === 2) {
      if (kind === 'http') {
        setTouched(true);
        if (!/^[a-z][a-z0-9_]{2,}$/.test(http.name) || !/^https:\/\/[^\s]+$/.test(http.url)) return;
        const host = (() => {
          try {
            return new URL(http.url.replace(/\{[^}]+\}/g, 'x')).hostname.split('.')[0];
          } catch {
            return '';
          }
        })();
        if (!displayName) setDisplayName(host.charAt(0).toUpperCase() + host.slice(1));
        if (!name) setName(kebab(host));
        if (!system) setSystem(host.charAt(0).toUpperCase() + host.slice(1));
      } else if (!selected.size) {
        setError('Choose at least one operation to expose.');
        return;
      }
      setStep(3);
    }
  }

  const type: ModuleType = kind === 'http' ? 'http' : kind === 'openapi' ? 'openapi' : 'mcp';
  const chosen: DiscoveredOperation[] = kind === 'http' ? [] : (found?.operations ?? []).filter((o) => selected.has(o.name)).map((o) => ({ ...o, access: selected.get(o.name)! }));
  const httpInputs = inputsOf(http);

  async function create() {
    setError(null);
    const errs = { display: displayName.trim() ? undefined : 'Give the module a display name.', name: kebab(name) ? undefined : 'Give the module a name, e.g. servicenow.' };
    setFieldErr(errs);
    if (errs.display || errs.name) return;
    try {
      await onCreate({
        name: kebab(name),
        displayName: displayName.trim(),
        system: system.trim() || displayName.trim(),
        type,
        endpoint: found?.endpoint ?? '',
        connectionId,
        operations: kind === 'http' ? undefined : chosen,
        http: kind === 'http' ? http : undefined,
      });
    } catch (e) {
      const message = (e as Error).message;
      if (/named .* already exists|^Name the module/.test(message)) setFieldErr({ name: message });
      else if (/display name/.test(message)) setFieldErr({ display: message });
      else setError(message);
    }
  }

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Add module"
      description={`Step ${step} of ${STEPS.length} · ${['Where the operations come from', kind === 'http' ? 'Build the operation' : 'Choose what workflows may call', 'Name it and save a draft'][step - 1]}`}
      headerExtra={<Stepper steps={STEPS} current={step} className="pt-3" testId="module-stepper" />}
      bodyRef={bodyRef}
      panelClassName="h-[min(85vh,42rem)]"
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          <Button variant="outline" onClick={() => (step === 1 ? onOpenChange(false) : (setError(null), setStep(step - 1)))} disabled={creating || discovering}>
            {step === 1 ? 'Cancel' : 'Back'}
          </Button>
          {step < 3 ? (
            <LoadingButton isLoading={discovering} loadingText={kind === 'mcp' ? 'Reading the server…' : 'Reading the spec…'} onClick={next}>
              Next
            </LoadingButton>
          ) : (
            <LoadingButton isLoading={creating} loadingText="Saving…" onClick={create}>
              Save draft
            </LoadingButton>
          )}
        </div>
      }
    >
      {error && <p className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}

      {step === 1 && (
        <div className="flex flex-col gap-5">
          <RadioGroup value={kind} onValueChange={(k) => setKind(k as Kind)} className="grid gap-2 sm:grid-cols-2">
            {KINDS.map((k) => (
              <label key={k.kind} htmlFor={`mk-${k.kind}`} className={cn('flex items-start gap-3 rounded-md border p-3', k.disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer', kind === k.kind && 'border-primary bg-primary/5')}>
                <RadioGroupItem value={k.kind} id={`mk-${k.kind}`} disabled={!!k.disabled} className="mt-0.5" />
                <k.icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{k.label}</span>
                  <span className="block text-xs text-muted-foreground">{k.disabled ?? k.hint}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
          <FormField id="mod-conn" label="Connection" error={fieldErr.connection} hint="The integration whose credential the gateway uses. Its scopes cap what any operation here can do.">
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap gap-2">
                <Select
                  value={connectionId}
                  onValueChange={(v) => {
                    setConnectionId(v);
                    setFieldErr({});
                  }}
                  disabled={connectionsLoading}
                >
                  <SelectTrigger id="mod-conn" className="min-w-56 flex-1" aria-invalid={!!fieldErr.connection}>
                    <SelectValue placeholder={connectionsLoading ? 'Loading connections…' : usable.length ? 'Choose a connection' : 'No connections yet'} />
                  </SelectTrigger>
                  <SelectContent>
                    {usable.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        <span className="flex items-center gap-2">
                          <SystemMark kind={c.kind} size="sm" /> {c.name}
                          {c.status !== 'healthy' && <IntegrationStatusBadge status={c.status} />}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button type="button" variant="outline" onClick={onConnectNew}>
                  <Plus className="size-4" /> Connect a new system
                </Button>
              </div>
              {connection && connection.status !== 'healthy' && connection.status !== 'expiring' && (
                <p className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-400">
                  <AlertTriangle className="size-3.5" /> This connection is not healthy, so calls will fail until it is fixed in Integrations. <ConnectionChip connection={connection} />
                </p>
              )}
            </div>
          </FormField>
          {kind === 'mcp' && (
            <FormField id="mcp-url" label="Server URL" error={fieldErr.url} hint="Streamable HTTP endpoint. The gateway lists its tools now and keeps that list as the reviewed snapshot.">
              <Input id="mcp-url" value={url} aria-invalid={!!fieldErr.url} onChange={(e) => (setUrl(e.target.value), setFieldErr({}))} placeholder="e.g. https://servicenow.northfield.internal/mcp" className="font-mono text-sm" />
            </FormField>
          )}
          {kind === 'openapi' && (
            <div className="flex flex-col gap-3">
              <FormField id="spec-url" label="Spec URL" optional error={fieldErr.spec}>
                <Input id="spec-url" value={specUrl} aria-invalid={!!fieldErr.spec} onChange={(e) => (setSpecUrl(e.target.value), setFieldErr({}))} placeholder="e.g. https://deposits.api.northfield.internal/openapi.json" className="font-mono text-sm" />
              </FormField>
              <FormField id="spec-file" label="Or upload the spec" optional hint="OpenAPI 3.0 or 3.1.">
                <FileUpload
                  id="spec-file"
                  purpose="tool_spec"
                  onChange={(items) => {
                    const ready = uploadsReady(items) ? items[0] : undefined;
                    setSpecFileId(ready?.fileId ?? '');
                    setFileName(ready?.name ?? '');
                    setSpecWaiting(items.length ? uploadsBlocker(items) : undefined);
                    setFieldErr({});
                  }}
                />
              </FormField>
            </div>
          )}
        </div>
      )}

      {step === 2 && kind === 'http' && <HttpOperationBuilder value={http} onChange={setHttp} errors={httpErrors} />}
      {step === 2 && kind !== 'http' && found && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            {found.system} lists {plural(found.operations.length, 'operation')} at version {found.version}. Reads are selected; writes and money movement are opt-in.
          </p>
          {found.warnings.map((w) => (
            <Alert key={w}>
              <AlertTriangle className="size-4" />
              <AlertDescription>{w}</AlertDescription>
            </Alert>
          ))}
          <OperationPicker operations={found.operations} selected={selected} onChange={setSelected} />
        </div>
      )}

      {step === 3 && (
        <div className="flex flex-col gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="m-display" label="Display name" error={fieldErr.display}>
              <Input id="m-display" value={displayName} aria-invalid={!!fieldErr.display} onChange={(e) => (setDisplayName(e.target.value), setFieldErr((f) => ({ ...f, display: undefined })))} placeholder="e.g. ServiceNow" />
            </FormField>
            <FormField id="m-name" label="Module name" error={fieldErr.name} hint={`Workflows pin ${kebab(name) || 'this'}; it cannot change later.`}>
              <Input id="m-name" value={name} aria-invalid={!!fieldErr.name} onChange={(e) => (setName(e.target.value), setFieldErr((f) => ({ ...f, name: undefined })))} placeholder="e.g. servicenow" className="font-mono" />
            </FormField>
          </div>
          <FormField id="m-system" label="System">
            <Input id="m-system" value={system} onChange={(e) => setSystem(e.target.value)} placeholder="e.g. ServiceNow" />
          </FormField>
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium">{kind === 'http' ? 'Operation' : plural(chosen.length, 'operation')}</span>
            <ul className="divide-y rounded-md border">
              {(kind === 'http' ? [{ name: http.name, description: `${http.method} ${http.url}`, access: http.access, extra: [...httpInputs.path, ...httpInputs.body].join(', ') }] : chosen.map((o) => ({ name: o.name, description: o.description, access: o.access, extra: o.input.map((x) => x.name).join(', ') }))).map((o) => (
                <li key={o.name} className="flex items-start justify-between gap-3 px-3 py-2">
                  <span className="min-w-0">
                    <code className="font-mono text-sm">{o.name}</code>
                    <span className="block truncate text-xs text-muted-foreground">{o.description}</span>
                    {o.extra && <span className="block truncate text-xs text-muted-foreground">Inputs: {o.extra}</span>}
                  </span>
                  <AccessBadge access={o.access} />
                </li>
              ))}
            </ul>
          </div>
          <p className="text-xs text-muted-foreground">
            Saved as a draft owned by your team. Security reviews it once; then each workflow requests the operations it needs, with an expiry. Record bindings and limits are set on the module page.
          </p>
        </div>
      )}
    </DialogShell>
  );
}
