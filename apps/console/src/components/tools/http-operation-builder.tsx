'use client';

import * as React from 'react';
import { AlertTriangle, Plus, X } from 'lucide-react';

import { EgressHostNotice } from '@/components/settings/egress-host-notice';
import { FormField } from '@/components/shared/form-field';
import { SecretPicker } from '@/components/shared/secret-picker';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import type { ToolAccess } from '@/lib/types/domain';
import type { BodyEncoding, HttpMethod, HttpOperationInput } from '@/lib/types/tool-modules';

const METHODS: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
const SECRET_REF = /^\{\{[A-Z][A-Z0-9_]*\}\}$/;
const SENSITIVE = ['authorization', 'x-api-key', 'cookie'];

const ENCODING: Record<BodyEncoding, { label: string; hint: string }> = {
  json: { label: 'JSON', hint: 'Sent as application/json. Use {{name}} for a value the agent supplies.' },
  form: { label: 'Form', hint: 'Sent as application/x-www-form-urlencoded, the way Stripe and many older APIs take a write. The encoding sets the Content-Type header.' },
  raw: { label: 'Raw', hint: 'Sent as typed, with the Content-Type header you set.' },
};

/** Path parameters (`{id}`) and body variables (`{{amount}}`) become the operation's inputs. Upper-case `{{NAME}}` is a vault reference, not an input. */
export function inputsOf(op: Pick<HttpOperationInput, 'url' | 'body'>) {
  // `{{NAME}}` in the path or query is a secret reference, so only a single-braced `{id}` is a path parameter.
  const path = [...op.url.matchAll(/(?<!\{)\{([a-zA-Z0-9_]+)\}(?!\})/g)].map((m) => m[1]);
  const body = [...(op.body ?? '').matchAll(/\{\{\s*([a-z][a-zA-Z0-9_]*)\s*\}\}/g)].map((m) => m[1]);
  return { path: [...new Set(path)], body: [...new Set(body)].filter((b) => !path.includes(b)) };
}

export const hasBody = (method: HttpMethod) => method !== 'GET' && method !== 'DELETE';

/** A form body's fields, from the JSON object tools-service stores; text that is not one reads as no fields yet. */
function formRows(body: string | undefined): [string, string][] {
  try {
    const v: unknown = JSON.parse(body || '{}');
    return v && typeof v === 'object' && !Array.isArray(v) ? Object.entries(v as Record<string, unknown>).map(([k, x]) => [k, String(x)]) : [];
  } catch {
    return [];
  }
}

const formBody = (rows: [string, string][]) => JSON.stringify(Object.fromEntries(rows), null, 2);

/** Method and full URL on one line, as an API client shows them; `trailing` sits at its end (Mock or Real, Run). `bare`
 * drops the label and hint, for a page that says what the line does beneath it. */
export function RequestLine({ value, onChange, error, trailing, bare }: { value: HttpOperationInput; onChange: (v: HttpOperationInput) => void; error?: string; trailing?: React.ReactNode; bare?: boolean }) {
  const line = (
      <div className="flex flex-col gap-2 md:flex-row">
        <div className="flex min-w-0 flex-1">
          <Select value={value.method} onValueChange={(v) => onChange({ ...value, method: v as HttpMethod })}>
            <SelectTrigger className="w-28 shrink-0 rounded-r-none border-r-0 font-mono font-semibold" aria-label="Method">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {METHODS.map((m) => (
                <SelectItem key={m} value={m}>
                  <span className="font-mono font-semibold">{m}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input id="http-url" value={value.url} onChange={(e) => onChange({ ...value, url: e.target.value })} placeholder="e.g. https://deposits.api.example.internal/v1/accounts/{accountId}/statements" className="min-w-0 flex-1 rounded-l-none font-mono text-sm" aria-invalid={!!error} />
        </div>
        {trailing && <div className="flex items-center gap-2">{trailing}</div>}
      </div>
  );
  if (bare) return error ? <div className="flex flex-col gap-1.5">{line}<p className="text-xs text-destructive">{error}</p></div> : line;
  return (
    <FormField id="http-url" label="Request" error={error} hint="Use {name} for a value in the path or the query. Values the case binds are filled by the gateway.">
      {line}
    </FormField>
  );
}

/** Each `{name}` in the address and `{{name}}` in the body: the inputs an agent fills. */
export function DerivedInputs({ value }: { value: Pick<HttpOperationInput, 'url' | 'body'> }) {
  const params = inputsOf(value);
  if (!params.path.length && !params.body.length) return null;
  return (
    <div className="overflow-hidden rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Input</TableHead>
            <TableHead>From</TableHead>
            <TableHead>Required</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...params.path.map((p) => [p, 'Path'] as const), ...params.body.map((p) => [p, 'Body'] as const)].map(([p, from]) => (
            <TableRow key={p}>
              <TableCell>
                <code className="font-mono text-xs">{p}</code>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">{from}</TableCell>
              <TableCell className="text-xs">Yes</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** Plain headers; a key belongs on the module's connection, which signs every call in. */
export function HeadersEditor({ value, onChange, note }: { value: HttpOperationInput; onChange: (v: HttpOperationInput) => void; note?: React.ReactNode }) {
  const set = (headers: HttpOperationInput['headers']) => onChange({ ...value, headers });
  const literal = value.headers.filter((h) => SENSITIVE.includes(h.key.trim().toLowerCase()) && h.value.trim() && !SECRET_REF.test(h.value.trim()));
  return (
    <div className="flex flex-col gap-2" data-testid="http-headers">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">Headers</span>
        <Button type="button" size="sm" variant="ghost" onClick={() => set([...value.headers, { key: '', value: '' }])}>
          <Plus className="size-3.5" /> Add header
        </Button>
      </div>
      {value.headers.map((h, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input value={h.key} onChange={(e) => set(value.headers.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} placeholder="e.g. Accept" aria-label="Header name" className="w-2/5 font-mono text-sm" />
          <Input value={h.value} onChange={(e) => set(value.headers.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} placeholder="e.g. application/json" aria-label="Header value" className="min-w-0 flex-1 font-mono text-sm" />
          <SecretPicker label="Insert a secret as the header value" onPick={(ref) => set(value.headers.map((x, j) => (j === i ? { ...x, value: ref } : x)))} />
          <Button type="button" size="icon" variant="ghost" className="size-8" aria-label="Remove header" onClick={() => set(value.headers.filter((_, j) => j !== i))}>
            <X className="size-4" />
          </Button>
        </div>
      ))}
      {literal.length > 0 && (
        <p className="flex items-center gap-1.5 text-xs text-warning-text">
          <AlertTriangle className="size-3.5 shrink-0" /> {literal.map((h) => h.key).join(', ')} holds a literal value. Put the key on the module&apos;s connection, or reference a secret as <code className="font-mono">{'{{NAME}}'}</code>.
        </p>
      )}
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}

/** The body as JSON, form fields or raw text: a form's fields are rows, stored as a JSON object. */
export function BodyEditor({ value, onChange, error }: { value: HttpOperationInput; onChange: (v: HttpOperationInput) => void; error?: string }) {
  const encoding = value.bodyEncoding ?? 'json';
  const rows = encoding === 'form' ? formRows(value.body) : [];
  const setRows = (next: [string, string][]) => onChange({ ...value, body: formBody(next) });
  return (
    <div className="flex flex-col gap-4" data-testid="http-body-editor">
      <FormField id="http-enc" label="Body encoding" hint={ENCODING[encoding].hint}>
        <ToggleGroup
          type="single"
          variant="outline"
          value={encoding}
          // A JSON or raw body's text is not a set of fields, so switching to a form starts with none.
          onValueChange={(v) => v && onChange({ ...value, bodyEncoding: v as BodyEncoding, body: v === 'form' ? formBody(formRows(value.body)) : encoding === 'form' ? '' : value.body })}
          className="w-fit"
          aria-label="Body encoding"
        >
          {(Object.keys(ENCODING) as BodyEncoding[]).map((k) => (
            <ToggleGroupItem key={k} value={k} className="flex-none px-3">
              {ENCODING[k].label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </FormField>
      {encoding === 'form' ? (
        <div className="flex flex-col gap-2" data-testid="http-form-body">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Body fields</span>
            <Button type="button" size="sm" variant="ghost" onClick={() => setRows([...rows, ['', '']])}>
              <Plus className="size-3.5" /> Add field
            </Button>
          </div>
          {rows.length === 0 && <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">No body fields yet. Add a field for each value the system takes, such as email with the value {'{{email}}'}.</p>}
          {rows.map(([k, v], i) => (
            <div key={i} className="flex items-center gap-2">
              <Input value={k} onChange={(e) => setRows(rows.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} placeholder="e.g. email" aria-label="Field name" className="w-2/5 font-mono text-sm" />
              <Input value={v} onChange={(e) => setRows(rows.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} placeholder="e.g. {{email}}" aria-label="Field value" className="min-w-0 flex-1 font-mono text-sm" />
              <Button type="button" size="icon" variant="ghost" className="size-8" aria-label="Remove field" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                <X className="size-4" />
              </Button>
            </div>
          ))}
          <p className="text-xs text-muted-foreground">Use {'{{name}}'} for a value the agent supplies.</p>
          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>
      ) : (
        <FormField id="http-body" label="Body template" optional error={error}>
          <Textarea id="http-body" value={value.body ?? ''} onChange={(e) => onChange({ ...value, body: e.target.value })} rows={4} className="font-mono text-xs" placeholder={encoding === 'json' ? 'e.g. {\n  "amount": {{amount}}\n}' : 'e.g. <customer><email>{{email}}</email></customer>'} />
        </FormField>
      )}
    </div>
  );
}

/**
 * One HTTP operation, built the way the shared component library's HTTP tool editor builds a request. `callOnly`
 * drops name, access and description: an existing operation's call is edited on its page, which shows those itself.
 */
export function HttpOperationBuilder({ value, onChange, errors, callOnly }: { value: HttpOperationInput; onChange: (v: HttpOperationInput) => void; errors?: Partial<Record<'name' | 'url' | 'body', string>>; callOnly?: boolean }) {
  const set = <K extends keyof HttpOperationInput>(k: K, v: HttpOperationInput[K]) => onChange({ ...value, [k]: v });
  return (
    <div className="flex flex-col gap-4">
      {!callOnly && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField id="http-name" label="Operation name" hint="Lower case with underscores; agents see this name." error={errors?.name}>
              <Input id="http-name" value={value.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. get_statement" className="font-mono" aria-invalid={!!errors?.name} />
            </FormField>
            <FormField id="http-access" label="Access" hint={value.access === 'write' ? 'Calls wait for an approval token unless a gate policy covers them.' : 'Reads run without approval.'}>
              <Select value={value.access} onValueChange={(v) => set('access', v as ToolAccess)}>
                <SelectTrigger id="http-access" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="read">Read</SelectItem>
                  <SelectItem value="write">Write</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
          </div>
          <FormField id="http-desc" label="Description" optional hint="Agents read this to decide when to call the operation.">
            <Input id="http-desc" value={value.description} onChange={(e) => set('description', e.target.value)} placeholder="e.g. Monthly statement for a deposit account" />
          </FormField>
        </>
      )}
      <RequestLine value={value} onChange={onChange} error={errors?.url} />
      <EgressHostNotice url={value.url} />
      <DerivedInputs value={value} />
      <HeadersEditor value={value} onChange={onChange} />
      {hasBody(value.method) && <BodyEditor value={value} onChange={onChange} error={errors?.body} />}
    </div>
  );
}
