'use client';

import { FileText } from 'lucide-react';

import { EntityPicker } from '@/components/shared/entity-picker';
import { fileOptions } from '@/hooks/options-queries';

/**
 * Pick files already in Files (c-159): an `EntityPicker` over files-service's `/v1/files/options`, so search runs on the
 * server and chips are labelled by id. A file not scanned clean is listed but cannot be picked. Pair it with
 * `FileUpload` when a page also takes new files; `AddDocumentsDialog` does both.
 */
export function FilePicker({ value, onChange, disabled, testId = 'file-picker' }: { value: string[]; onChange: (ids: string[]) => void; disabled?: boolean; testId?: string }) {
  return (
    <EntityPicker
      source={fileOptions}
      value={value}
      onChange={onChange}
      addLabel="Pick from Files"
      searchPlaceholder="Search your team's files by name…"
      emptyText="No file matches. Upload it instead."
      icon={FileText}
      disabled={disabled}
      testId={testId}
    />
  );
}
