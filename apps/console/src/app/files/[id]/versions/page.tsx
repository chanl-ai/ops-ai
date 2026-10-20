'use client';

import { FilePage } from '@/components/files/file-page';
import { Row, Rows } from '@/components/shared/surface';
import { Badge } from '@/components/ui/badge';
import { dateTime, bytes } from '@/lib/format';

/** A file's Versions tab: each stored version, newest first, by its content digest. */
export default function FileVersionsPage() {
  return (
    <FilePage>
      {({ file }) => (
        <Rows className="rounded-lg border" testId="file-versions">
          {file.versions.map((v) => (
            <Row
              key={v.version}
              title={`Version ${v.version}`}
              description={`${v.uploadedBy} · ${dateTime(v.uploadedAt)} · ${bytes(v.size)}`}
              trailing={
                <span className="flex items-center gap-2">
                  {v.current && <Badge variant="secondary">Current</Badge>}
                  <span className="font-mono text-xs text-muted-foreground">sha256:{v.digest.slice(0, 12)}…</span>
                </span>
              }
            />
          ))}
        </Rows>
      )}
    </FilePage>
  );
}
