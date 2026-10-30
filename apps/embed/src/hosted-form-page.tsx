'use client';

import * as React from 'react';
import { Paperclip, X } from 'lucide-react';

import { HostedForm, HostedFormRefused } from '@/components/forms/hosted-form';
import type { FileRef } from '@/components/shared/file-refs-field';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { FileControl } from '@/components/workflows/run-input-form';
import type { HostedFormReceived, HostedFormView } from '@/lib/types/forms';

type Opened = { kind: 'loading' } | { kind: 'ready'; form: HostedFormView } | { kind: 'refused'; title: string; message: string };

const NOT_A_FORM = 'This link does not open a form. Check that you copied all of it, or ask whoever sent it to you for a new one.';

/** Why agents-service refused: its own plain message, except a 404, whose message would name ids a stranger never sees. */
async function refusal(res: Response): Promise<string> {
  if (res.status === 404) return NOT_A_FORM;
  const body = (await res.json().catch(() => null)) as { error?: { message?: string } } | null;
  return body?.error?.message ?? 'The form could not be sent. Try again in a minute.';
}

/**
 * The page a person opens from a hosted form's link: the form through the embed app's `/v1` rewrite, file fields
 * uploaded first (the answer's `fileId` goes in the field), then Send. Every call carries the link's token.
 */
export function HostedFormPage({ slug, token }: { slug: string; token: string }) {
  const [opened, setOpened] = React.useState<Opened>({ kind: 'loading' });
  const at = `/v1/forms/public/${encodeURIComponent(slug)}`;
  const t = encodeURIComponent(token);

  React.useEffect(() => {
    let live = true;
    const open = async (): Promise<Opened> => {
      if (!token) return { kind: 'refused', title: 'This link is not complete', message: NOT_A_FORM };
      try {
        const res = await fetch(`${at}?t=${t}`, { cache: 'no-store' });
        if (res.ok) return { kind: 'ready', form: ((await res.json()) as { data: HostedFormView }).data };
        const title = res.status === 401 ? 'This link has expired' : res.status === 404 ? 'This link does not open a form' : 'This form cannot be opened';
        return { kind: 'refused', title, message: await refusal(res) };
      } catch {
        return { kind: 'refused', title: 'This form cannot be opened', message: 'The form could not be reached. Check your connection and try again.' };
      }
    };
    void open().then((o) => {
      if (live) setOpened(o);
    });
    return () => {
      live = false;
    };
  }, [at, t, token]);

  const submit = async (values: Record<string, unknown>): Promise<HostedFormReceived> => {
    const res = await fetch(`${at}/submit?t=${t}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ values }) });
    if (!res.ok) throw new Error(await refusal(res));
    return ((await res.json()) as { data: HostedFormReceived }).data;
  };

  const upload = async (file: File): Promise<FileRef> => {
    const res = await fetch(`${at}/files?t=${t}&name=${encodeURIComponent(file.name)}`, { method: 'POST', headers: { 'Content-Type': file.type || 'application/octet-stream' }, body: file });
    if (!res.ok) throw new Error(await refusal(res));
    return ((await res.json()) as { data: { fileId: string; name: string } }).data;
  };
  const fileControl: FileControl = (p) => <PublicFileField {...p} upload={upload} />;

  return (
    <main className="min-h-svh bg-background">
      <div className="mx-auto flex w-full max-w-lg min-w-0 flex-col gap-4 px-4 py-10">
        {opened.kind === 'loading' && (
          <Card aria-busy>
            <CardContent className="flex flex-col gap-4 pt-6">
              <Skeleton className="h-6 w-2/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </CardContent>
          </Card>
        )}
        {opened.kind === 'refused' && <HostedFormRefused title={opened.title} message={opened.message} />}
        {opened.kind === 'ready' && (
          <>
            <HostedForm form={opened.form} onSubmit={submit} fileControl={fileControl} />
            {opened.form.form.takesFiles && <p className="text-center text-xs text-muted-foreground">Files are scanned before anyone opens them.</p>}
          </>
        )}
      </div>
    </main>
  );
}

/** A file field on the public page: choose files, each uploaded at once through the form's link, and remove them. */
function PublicFileField({ id, many, value, onChange, testId, upload }: Parameters<FileControl>[0] & { upload: (file: File) => Promise<FileRef> }) {
  const input = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(0);
  const [error, setError] = React.useState<string | null>(null);
  const pick = async (files: File[]) => {
    setError(null);
    setBusy(files.length);
    const added: FileRef[] = [];
    for (const f of files) {
      try {
        added.push(await upload(f));
      } catch (e) {
        setError(`${f.name}: ${e instanceof Error ? e.message : 'could not be attached'}`);
      }
      setBusy((n) => n - 1);
    }
    if (added.length) onChange(many ? [...value, ...added] : added.slice(-1));
  };
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid={testId}>
      <input
        ref={input}
        id={id}
        type="file"
        className="sr-only"
        multiple={many}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = '';
          if (files.length) void pick(files);
        }}
      />
      {value.map((f) => (
        <div key={f.fileId} className="flex min-w-0 items-center gap-2 rounded-md border p-2 text-sm">
          <Paperclip className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="min-w-0 flex-1 truncate">{f.name ?? 'Attached file'}</span>
          <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${f.name ?? 'the file'}`} onClick={() => onChange(value.filter((x) => x.fileId !== f.fileId))}>
            <X />
          </Button>
        </div>
      ))}
      {(many || value.length === 0) && (
        <Button type="button" variant="outline" className="w-full" disabled={busy > 0} onClick={() => input.current?.click()}>
          <Paperclip /> {busy > 0 ? 'Attaching…' : value.length ? 'Attach another file' : 'Choose a file'}
        </Button>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
