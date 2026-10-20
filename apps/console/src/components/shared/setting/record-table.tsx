'use client';

import * as React from 'react';
import type { ColumnDef } from '@tanstack/react-table';

import { DataTableWithViews } from '@/components/data-table-with-views';
import { selectColumn } from '@/components/shared/select-column';
import { idColumn } from '@/components/shared/id-column';

/**
 * A table of records: a select-all checkbox column first, then the record id (middle-truncated, copyable), then the
 * caller's columns. Every list of records starts this way so a person can select, and can quote an id.
 */
export function RecordTable<T extends { id: string }>({ columns, data, nameOf, searchColumn = 'name', searchPlaceholder, emptyState }: { columns: ColumnDef<T>[]; data: T[]; nameOf: (row: T) => string; searchColumn?: string; searchPlaceholder: string; emptyState?: React.ReactNode }) {
  const cols = React.useMemo<ColumnDef<T>[]>(
    () => [
      selectColumn<T>(nameOf),
      idColumn<T>((r) => r.id),
      ...columns,
    ],
    [columns, nameOf],
  );
  return <DataTableWithViews columns={cols} data={data} getRowId={(r) => r.id} searchColumn={searchColumn} searchPlaceholder={searchPlaceholder} hideViewSwitcher emptyState={emptyState} />;
}
