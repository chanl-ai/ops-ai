'use client';

import { AlertTriangle, Plus, X } from 'lucide-react';

import { FormField } from '@/components/shared/form-field';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import type { ToolAccess } from '@/lib/types/domain';
import type { HttpMethod, HttpOperationInput } from '@/lib/types/tool-modules';

const METHODS: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];
const SECRET_REF = /^\{\{[A-Z][A-Z0-9_]*\}\}$/;
const SENSITIVE = ['authorization', 'x-api-key', 'cookie'];

/** Path parameters (`{id}`) and body variables (`{{amount}}`) become the operation's inputs. Upper-case `{{NAME}}` is a vault reference, not an input. */
export function inputsOf(op: Pick<HttpOperationInput, 'url' | 'body'>) {
  const path = [...op.url.matchAll(/\{([a-zA-Z0-9_]+)\}/g)].map((m) => m[1]);
  const body = [...(op.body ?? '').matchAll(/\{\{\s*([a-z][a-zA-Z0-9_]*)\s*\}\}/g)].map((m) => m[1]);
  return { path: [...new Set(path)], body: [...new Set(body)].filter((b) => !path.includes(b)) };
}

/** One HTTP operation, built the way the shared component library's HTTP tool editor builds a request. Credentials are vault references only. */
export function HttpOperationBuilder({ value, onChange, errors }: { value: HttpOperationInput; onChange: (v: HttpOperationInput) => void; errors?: Partial<Record<'name' | 'url', string>> }) {
  const set = <K extends keyof HttpOperationInput>(k: K, v: HttpOperationInput[K]) => onChange({ ...value, [k]: v });
  const params = inputsOf(value);
  const literal = value.headers.filter((h) => SENSITIVE.includes(h.key.trim().toLowerCase()) && h.value.trim() && !SECRET_REF.test(h.value.trim()));
  const hasBody = value.method !== 'GET' && value.method !== 'DELETE';

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField id="http-name" label="Operation name" hint="Lower case with underscores; agents see this name." error={errors?.name}>
          <Input id="http-name" value={value.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. get_statement" className="font-mono" aria-invalid={!!errors?.name} />
        </FormField>
        <FormField id="http-access" label="Access" hint={value.access === 'money_movement' ? 'Every call needs a person’s approval and a second approver.' : value.access === 'write' ? 'Calls wait for an approval token unless a gate policy covers them.' : 'Reads run without approval.'}>
          <Select value={value.access} onValueChange={(v) => set('access', v as ToolAccess)}>
            <SelectTrigger id="http-access" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="read">Read</SelectItem>
              <SelectItem value="write">Write</SelectItem>
              <SelectItem value="money_movement">Moves money</SelectItem>
            </SelectContent>
          </Select>
        </FormField>
      </div>
      <FormField id="http-desc" label="Description" optional hint="Agents read this to decide when to call the operation.">
        <Input id="http-desc" value={value.description} onChange={(e) => set('description', e.target.value)} placeholder="e.g. Monthly statement for a deposit account" />
      </FormField>
      <FormField id="http-url" label="Request" error={errors?.url} hint="Use {name} for path parameters. Values the case binds are filled by the gateway.">
        <div className="flex">
          <Select value={value.method} onValueChange={(v) => set('method', v as HttpMethod)}>
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
          <Input id="http-url" value={value.url} onChange={(e) => set('url', e.target.value)} placeholder="e.g. https://deposits.api.example.internal/v1/accounts/{accountId}/statements" className="min-w-0 flex-1 rounded-l-none font-mono text-sm" aria-invalid={!!errors?.url} />
        </div>
      </FormField>
      {(params.path.length > 0 || params.body.length > 0) && (
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
      )}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Headers</span>
          <Button type="button" size="sm" variant="ghost" onClick={() => set('headers', [...value.headers, { key: '', value: '' }])}>
            <Plus className="size-3.5" /> Add header
          </Button>
        </div>
        {value.headers.map((h, i) => (
          <div key={i} className="flex items-center gap-2">
            <Input value={h.key} onChange={(e) => set('headers', value.headers.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} placeholder="e.g. Accept" aria-label="Header name" className="w-2/5 font-mono text-sm" />
            <Input value={h.value} onChange={(e) => set('headers', value.headers.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} placeholder="e.g. application/json" aria-label="Header value" className="min-w-0 flex-1 font-mono text-sm" />
            <Button type="button" size="icon" variant="ghost" className="size-8" aria-label="Remove header" onClick={() => set('headers', value.headers.filter((_, j) => j !== i))}>
              <X className="size-4" />
            </Button>
          </div>
        ))}
        {literal.length > 0 && (
          <p className="flex items-center gap-1.5 text-xs text-amber-700 dark:text-amber-400">
            <AlertTriangle className="size-3.5 shrink-0" /> {literal.map((h) => h.key).join(', ')} holds a literal value. Reference the vault instead, e.g. <code className="font-mono">{'{{CORE_API_KEY}}'}</code>.
          </p>
        )}
      </div>
      {hasBody && (
        <FormField id="http-body" label="Body template" optional hint="Use {{name}} for values the agent supplies.">
          <Textarea id="http-body" value={value.body ?? ''} onChange={(e) => set('body', e.target.value)} rows={4} className="font-mono text-xs" placeholder={'e.g. {\n  "amount": {{amount}}\n}'} />
        </FormField>
      )}
      <FormField id="http-secret" label="Credential" optional hint="A vault path. The gateway resolves it on each call; the value never reaches the console or the agent.">
        <Input id="http-secret" value={value.secretRef ?? ''} onChange={(e) => set('secretRef', e.target.value)} placeholder="e.g. vault://prod/data-gateway/deposits/api-key" className="font-mono text-sm" />
      </FormField>
    </div>
  );
}
