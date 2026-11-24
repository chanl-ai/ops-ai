'use client';

import { FilePage } from '@/components/files/file-page';
import { Row, Rows } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { isOpen } from '@/components/reviews/review-columns';
import { useFileTask } from '@/hooks/extraction-queries';
import { plural } from '@/lib/format';
import { notReadSaid } from '@/lib/not-read-said';
import type { Extraction } from '@/lib/types/extractions';

const STATUS: Record<Extraction['status'], string> = { queued: 'Waiting', running: 'Reading', done: 'Read', failed: 'Failed', unreadable: 'No text' };

function outcome(r: Extraction): string {
  if (r.status === 'failed') return r.error?.message ?? 'The read failed';
  if (r.status !== 'done') return STATUS[r.status];
  if (r.outcome === 'incomplete') return notReadSaid(r.incomplete?.reason, r.incomplete?.tries);
  const check = r.needsReview?.length ?? 0;
  return check ? `${plural(check, 'field')} to check` : 'Nothing to check';
}

const notRead = (r: Extraction) => r.status === 'done' && r.outcome === 'incomplete';

/** Where the newest read no reply answered stands: its task is waiting, was decided, or it came through the API and has none. */
function Standing({ fileId }: { fileId: string }) {
  const task = useFileTask(fileId, true);
  if (!task.isSuccess) return null;
  const review = task.data;
  return <span data-testid="file-activity-standing"> · {!review ? 'read through the API' : isOpen(review) ? 'waiting in Human Tasks' : `task ${review.status}`}</span>;
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
                description={
                  <>
                    {outcome(r)}
                    {notRead(r) && r.id === extractions[0]?.id && <Standing fileId={r.fileId} />}
                  </>
                }
                trailing={
                  <span className="flex items-center gap-2">
                    <Badge variant={r.status === 'failed' ? 'destructive' : 'secondary'}>{notRead(r) ? 'Not read' : STATUS[r.status]}</Badge>
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
