'use client';

import * as React from 'react';
import { DialogShell } from '@/components/shared/dialog-shell';
import { FileUpload, type UploadItem, uploadsBlocker, uploadsReady } from '@/components/shared/file-upload';
import { LoadingButton } from '@/components/shared/loading-button';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import type { EvalCaseInput, EvalCheck, EvalCheckType } from '@/lib/types/evals';
import type { RunAsPrincipal } from '@/lib/types/run-as';
import { plural } from '@/lib/format';

import { checkComplete } from './eval-case-dialog';
import { CheckChips } from './eval-meta';

const TYPES: EvalCheckType[] = ['calls_tool', 'not_calls_tool', 'cites', 'reply_contains', 'reply_not_contains', 'refuses', 'extracts', 'rubric'];

export interface ParsedRow {
  line: number;
  input: EvalCaseInput;
  error?: string;
}

function cells(line: string) {
  return (line.match(/("([^"]|"")*"|[^,]*)(,|$)/g) ?? []).map((c) => c.replace(/,$/, '').replace(/^"|"$/g, '').replace(/""/g, '"').trim());
}

/** `type:value`; extracts is `extracts:field=value`, calls_tool may add `tool(arg=value)`. */
function parseCheck(raw: string): EvalCheck | string {
  const i = raw.indexOf(':');
  const type = raw.slice(0, i).trim() as EvalCheckType;
  const value = raw.slice(i + 1).trim();
  if (i < 0 || !TYPES.includes(type)) return `Unknown check “${raw.slice(0, 24)}”`;
  if (type === 'extracts') {
    const [field, v] = value.split('=');
    return { type, field: field?.trim(), value: v?.trim() };
  }
  if (type === 'calls_tool' || type === 'not_calls_tool') {
    const m = value.match(/^([\w-]+)(?:\((.*)\))?$/);
    const args = m?.[2]?.split('&').map((p) => ({ path: p.split('=')[0].trim(), equals: (p.split('=')[1] ?? '').trim() })).filter((a) => a.path);
    return { type, tool: m?.[1] ?? value, args: args?.length ? args : undefined };
  }
  if (type === 'cites') {
    const [source, section] = value.split('|').map((s) => s.trim());
    return { type, source, section: section || undefined };
  }
  return { type, text: value };
}

/** Header row, then `name, input, runAs, knowledgeBases, checks`. Lists are separated with semicolons. */
export function parseEvalCsv(text: string, principals: RunAsPrincipal[], collections: string[], tools: string[]): ParsedRow[] {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  return lines.slice(1).map((l, idx) => {
    const [name = '', input = '', runAs = '', kbs = '', checks = ''] = cells(l);
    const p = runAs ? principals.find((x) => x.id === runAs || x.name.toLowerCase() === runAs.toLowerCase()) : undefined;
    const kbList = kbs.split(';').map((s) => s.trim()).filter(Boolean);
    const parsed = checks.split(';').map((s) => s.trim()).filter(Boolean).map(parseCheck);
    const row: ParsedRow = { line: idx + 2, input: { name, input, context: { runAsId: p?.id, collections: kbList }, checks: parsed.filter((c): c is EvalCheck => typeof c !== 'string') } };
    const bad = parsed.find((c): c is string => typeof c === 'string');
    const unknownKb = kbList.find((k) => !collections.includes(k));
    // A check on a tool the agent does not hold can never pass (or never fail), so the row is rejected.
    const unknownTool = row.input.checks.find((c) => (c.type === 'calls_tool' || c.type === 'not_calls_tool') && c.tool && !tools.includes(c.tool));
    row.error = !name ? 'No name' : !input ? 'No input' : runAs && !p ? `No one called “${runAs}” to run as` : unknownKb ? `Unknown knowledge base “${unknownKb}”` : bad ? bad : unknownTool && 'tool' in unknownTool ? `Unknown tool “${unknownTool.tool}”: the agent doesn’t hold it` : !row.input.checks.length ? 'No checks' : row.input.checks.some((c) => !checkComplete(c)) ? 'A check is missing its value' : undefined;
    return row;
  });
}

export function ImportEvalCasesDialog({
  open,
  onOpenChange,
  principals,
  collections,
  tools,
  onImport,
  isPending,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  principals: RunAsPrincipal[];
  collections: string[];
  /** Tools the agent holds; a check naming any other tool is rejected. */
  tools: string[];
  /** `fileId` is the uploaded CSV; the eval set is recorded as using it. */
  onImport: (rows: EvalCaseInput[], fileId: string) => Promise<unknown>;
  isPending: boolean;
}) {
  const [rows, setRows] = React.useState<ParsedRow[] | null>(null);
  const [fileError, setFileError] = React.useState<string | null>(null);
  const [upload, setUpload] = React.useState<UploadItem[]>([]);
  const fileId = uploadsReady(upload) ? upload[0].fileId : undefined;
  const waiting = upload.length ? uploadsBlocker(upload) : undefined;
  React.useEffect(() => {
    if (open) {
      setRows(null);
      setFileError(null);
      setUpload([]);
    }
  }, [open]);
  const valid = (rows ?? []).filter((r) => !r.error);
  const invalid = (rows?.length ?? 0) - valid.length;

  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Import eval cases"
      description="CSV with a header row: name, input, runAs, knowledgeBases, checks. Separate several knowledge bases or checks with semicolons."
      footer={
        <div className="flex w-full items-center justify-end gap-2">
          {rows && <span className="mr-auto text-xs text-muted-foreground">{waiting ?? (invalid ? `${plural(invalid, 'row')} with errors will be skipped` : 'Every row is valid')}</span>}
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPending}>
            Cancel
          </Button>
          <LoadingButton
            isLoading={isPending}
            disabled={!valid.length || !fileId}
            onClick={async () => {
              await onImport(valid.map((r) => r.input), fileId!);
              onOpenChange(false);
            }}
          >
            {valid.length ? `Import ${plural(valid.length, 'case')}` : 'Import'}
          </LoadingButton>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <FileUpload
          id="ec-file"
          purpose="test_import"
          title="Drop a CSV file here or choose one"
          hint="Checks look like calls_tool:place_wire_hold(action=hold); reply_contains:callback; extracts:amount=1240.18; cites:Fraud & payments|§3.2"
          onChange={setUpload}
          onPick={async ([f]) => {
            try {
              const parsed = parseEvalCsv(await f.text(), principals, collections, tools);
              setFileError(parsed.length ? null : 'The file has no rows under the header.');
              setRows(parsed.length ? parsed : null);
            } catch {
              setFileError('That file could not be read as CSV.');
            }
          }}
          testId="eval-import-upload"
        />
        {fileError && <p className="text-sm text-destructive">{fileError}</p>}
        {rows && (
          <div className="overflow-hidden rounded-md border" data-testid="eval-import-preview">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-14">Row</TableHead>
                  <TableHead>Case</TableHead>
                  <TableHead>Checks</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.slice(0, 50).map((r) => (
                  <TableRow key={r.line}>
                    <TableCell className="tabular-nums text-muted-foreground">{r.line}</TableCell>
                    <TableCell className="max-w-56">
                      <div className="truncate font-medium">{r.input.name || '—'}</div>
                      <div className="truncate text-xs text-muted-foreground">{r.input.input}</div>
                    </TableCell>
                    <TableCell>
                      <CheckChips checks={r.input.checks} max={4} />
                    </TableCell>
                    <TableCell className="text-xs">{r.error ? <span className="text-destructive">{r.error}</span> : <span className="text-emerald-700 dark:text-emerald-400">Ready</span>}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {rows.length > 50 && <p className="border-t px-3 py-2 text-xs text-muted-foreground">and {plural(rows.length - 50, 'more row')}</p>}
          </div>
        )}
      </div>
    </DialogShell>
  );
}
