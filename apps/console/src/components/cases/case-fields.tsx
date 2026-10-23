import { ListTree } from 'lucide-react';

import { FieldRow } from '@/components/shared/field-row';
import { labelOf, PlainValue } from '@/components/shared/readable-value';
import { AttributeCard } from '@/components/shared/record-layout';

/** The fields the workflow that opened or added to the case gave it, in the case's rail, as the case holds them. */
export function CaseFields({ fields }: { fields: Record<string, unknown> }) {
  const rows = Object.entries(fields).filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (!rows.length) return null;
  return (
    <AttributeCard title="Fields" icon={ListTree} testId="case-fields">
      {rows.map(([key, value]) => (
        <FieldRow key={key} label={labelOf(key)} value={<PlainValue value={value} />} testId={`case-field-${key}`} />
      ))}
    </AttributeCard>
  );
}
