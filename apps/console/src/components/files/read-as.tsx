import { Badge } from '@/components/ui/badge';
import { plural } from '@/lib/format';
import type { FileData } from '@/lib/types/files';

/** "Read as": the type and version, how it was read, and how many fields wait for a person. */
export function readAsText(data: FileData): string {
  // Detect read the file and matched none of the team's types.
  if (!data.typeId) return 'Not recognised';
  return `${data.typeName ?? data.typeId}${data.version != null ? ` v${data.version}` : ''} · ${data.path === 'template' ? 'template' : 'model'}`;
}

export function ReadAs({ data, compact }: { data: FileData | null | undefined; compact?: boolean }) {
  if (!data) return <span className="text-xs text-muted-foreground">Not read</span>;
  return (
    <span className="flex min-w-0 flex-col gap-0.5" data-testid="read-as">
      <span className="truncate text-sm">{readAsText(data)}</span>
      {!data.typeId && <span className="text-xs text-muted-foreground">Extract again and choose its type</span>}
      {data.fieldsToCheck > 0 ? (
        <Badge variant="outline" className="w-fit border-warning/50 text-warning-text">
          {plural(data.fieldsToCheck, 'field')} to check
        </Badge>
      ) : (
        !compact && <span className="text-xs text-muted-foreground">Nothing to check</span>
      )}
    </span>
  );
}
