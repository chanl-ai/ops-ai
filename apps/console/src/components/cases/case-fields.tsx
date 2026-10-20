import Link from 'next/link';
import { ListTree } from 'lucide-react';

import { FieldRow } from '@/components/shared/field-row';
import { AttributeCard } from '@/components/shared/record-layout';
import { count, fieldValue } from '@/lib/format';

const labelOf = (key: string) => key.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

// A value that is a file's id links to the file's page, whatever the field is called.
const FILE_ID = /^fil_[A-Za-z0-9]+$/;

/** A value as it reads: calendar dates formatted, numbers grouped, a file id as a link; the field's name never decides. */
function Value({ value }: { value: unknown }) {
  if (typeof value === 'string' && FILE_ID.test(value))
    return (
      <Link href={`/files/${encodeURIComponent(value)}`} className="underline underline-offset-2">
        Open the file
      </Link>
    );
  if (typeof value === 'number') return <>{count(value)}</>;
  if (typeof value === 'string') return <>{fieldValue(value)}</>;
  return <>{JSON.stringify(value)}</>;
}

/** The fields the workflow that opened or added to the case gave it, in the case's rail, as the case holds them. */
export function CaseFields({ fields }: { fields: Record<string, unknown> }) {
  const rows = Object.entries(fields).filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (!rows.length) return null;
  return (
    <AttributeCard title="Fields" icon={ListTree} testId="case-fields">
      {rows.map(([key, value]) => (
        <FieldRow key={key} label={labelOf(key)} value={<Value value={value} />} testId={`case-field-${key}`} />
      ))}
    </AttributeCard>
  );
}
