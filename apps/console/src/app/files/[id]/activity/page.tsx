'use client';

import { FilePage } from '@/components/files/file-page';
import { Row, Rows } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { plural } from '@/lib/format';
import type { Extraction } from '@/lib/types/extractions';

const STATUS: Record<Extraction['status'], string> = { queued: 'Waiting', running: 'Reading', done: 'Read', failed: 'Failed', unreadable: 'No text' };

function outcome(r: Extraction): string {
  if (r.status === 'failed') return r.error?.message ?? 'The read failed';
  if (r.status !== 'done') return STATUS[r.status];
  const check = r.needsReview?.length ?? 0;
  return check ? `${plural(check, 'field')} to check` : 'Nothing to check';
}

/** A file's Activity tab: every read of it in this team, newest first. */
export default function FileActivityPage() {
  return (
    <FilePage>
      {({ file, extractions }) =>
        extractions.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing has read this file yet.</p>
        ) : (
          <Rows className="rounded-lg border" testId="file-activity">
            {extractions.map((r) => (
              <Row
                key={r.id}
                title={r.documentType ? `Read as ${r.documentType.id === file.data?.typeId ? (file.data.typeName ?? r.documentType.id) : r.documentType.id} v${r.documentType.version}` : 'Read'}
                description={outcome(r)}
                trailing={
                  <span className="flex items-center gap-2">
                    <Badge variant={r.status === 'failed' ? 'destructive' : 'secondary'}>{STATUS[r.status]}</Badge>
                    <span className="font-mono text-xs text-muted-foreground">{r.id}</span>
                  </span>
                }
              />
            ))}
          </Rows>
        )
      }
    </FilePage>
  );
}
