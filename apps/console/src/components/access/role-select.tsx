'use client';

import { SearchSelect } from '@/components/shared/search-select';
import { type OptionSource, useOptionLabels } from '@/hooks/options-queries';

/**
 * Choose one role: the search runs on the server as the person types, and the chosen role's name is read by id, so a
 * workspace with many roles never loads them all. `prefix` words the chosen role in the trigger ("A copy of Builder").
 */
export function RoleSelect({
  source,
  value,
  onChange,
  placeholder,
  noneLabel,
  prefix = '',
  testId,
  ariaLabel,
  disabled,
  className,
}: {
  source: OptionSource;
  value: string;
  onChange: (id: string) => void;
  placeholder: string;
  noneLabel?: string;
  prefix?: string;
  testId?: string;
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
}) {
  const named = useOptionLabels(source, value ? [value] : []);
  const label = named.data?.data.find((o) => o.id === value)?.label ?? value;
  return (
    <SearchSelect
      source={source}
      value={value ? { id: value, label: `${prefix}${label}` } : null}
      onChange={(id) => onChange(id)}
      placeholder={placeholder}
      searchPlaceholder="Search roles…"
      emptyText="No role matches."
      noneLabel={noneLabel}
      renderOption={(o) => <span className="truncate">{`${prefix}${o.label}`}</span>}
      testId={testId}
      ariaLabel={ariaLabel}
      disabled={disabled}
      className={className}
    />
  );
}
