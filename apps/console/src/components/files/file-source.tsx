import type * as React from 'react';

import Link from 'next/link';

import { KeyValues, Section } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { dateOnly, dateTime, plural } from '@/lib/format';
import type { FileDetail } from '@/lib/types/files';

type Source = NonNullable<FileDetail['source']>;

/** Who the source said may see the file, as recorded at its last fetch; "not known" is kept apart from nobody. */
function access(s: Source) {
  const read = s.accessReadAt ? `read ${dateTime(s.accessReadAt)}` : 'not read yet';
  if (s.accessList == null) return 'Not known: the source did not say when the file was fetched.';
  if (!s.accessList.length) return `Nobody is listed, ${read}. Recorded, not applied.`;
  const first = s.accessList.slice(0, 3).join(', ');
  const more = s.accessList.length > 3 ? ` and ${s.accessList.length - 3} more` : '';
  return `${first}${more} (${plural(s.accessList.length, 'entry', 'entries')}), ${read}. Recorded, not applied.`;
}

/**
 * Where a watched folder's file came from: its watch, its path, when the source last changed the version held, who the
 * source said may see it, and when the source stopped listing it. Read once, from the file's own detail.
 */
export function FileSource({ file }: { file: FileDetail }) {
  const s = file.source;
  if (!s) return null;
  const current = file.versions.find((v) => v.current) ?? file.versions[file.versions.length - 1];
  const version = current ? `version ${current.version} of ${file.versions.length}` : '';
  const rows: [string, React.ReactNode][] = [
    [
      'Watched folder',
      s.watchName ? (
        <Link href="/data/files/watches" className="underline underline-offset-4" data-testid="file-source-watch">
          {s.watchName}
        </Link>
      ) : (
        <span className="text-muted-foreground">A watch that was deleted</span>
      ),
    ],
    ['Path', <span key="p" className="break-all">{(s.path ?? '—').split('/').join(' › ')}</span>],
    ['Changed at the source', s.changedAt ? `${dateTime(s.changedAt)}${version ? ` · ${version}` : ''}` : `Not said by the source${version ? ` · ${version}` : ''}`],
    ['Who may see it at the source', <span key="a" data-testid="file-source-access">{access(s)}</span>],
  ];
  if (s.removedAt)
    rows.push([
      'Removed',
      <span key="r" data-testid="file-source-removed">
        Deleted at the source {dateTime(s.removedAt)}. Kept {file.retention.deleteAfter ? `until ${dateOnly(file.retention.deleteAfter)}` : 'until deleted'} by its retention class.
      </span>,
    ]);
  return (
    <Section title="Source" className="mb-4" actions={s.removedAt ? <Badge variant="outline">Removed at the source</Badge> : undefined}>
      <div data-testid="file-source">
        <KeyValues rows={rows} />
      </div>
    </Section>
  );
}
