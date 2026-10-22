'use client';

import * as React from 'react';

import { EntityPicker } from '@/components/shared/entity-picker';
import { FileUpload } from '@/components/shared/file-upload';
import { fileOptions, type OptionSource, useOptionLabels } from '@/hooks/options-queries';

export type FileRef = { fileId: string; name?: string };

/**
 * Files a form hands on by id: upload new ones (stored in Files as Email attachment first) or pick ones already in Files.
 * The value is the list of picked and uploaded files; with `many` off it holds at most one. Every attached file is one
 * row under the drop zone with its status and a remove button, whether it was dropped or picked.
 */
export function FileRefsField({
  id,
  value,
  onChange,
  many,
  testId,
  source = fileOptions,
}: {
  id: string;
  value: FileRef[];
  onChange: (next: FileRef[]) => void;
  many: boolean;
  testId: string;
  /** Where the picker's files come from; a design preview passes sample files. */
  source?: OptionSource;
}) {
  // The ids the upload control holds: those files show as its rows, and leave the value when their row is removed.
  const uploads = React.useRef<string[]>([]);
  const [uploadIds, setUploadIds] = React.useState<string[]>([]);
  const picked = value.filter((f) => !uploadIds.includes(f.fileId));
  const labels = useOptionLabels(source, picked.filter((f) => !f.name).map((f) => f.fileId));
  const nameOf = (f: FileRef) => f.name ?? labels.data?.data.find((o) => o.id === f.fileId)?.label ?? f.fileId;
  return (
    <div className="flex flex-col gap-2" data-testid={testId}>
      <FileUpload
        id={`${id}-upload`}
        purpose="case_attachment"
        multiple={many}
        testId={`${testId}-upload`}
        shown={(i) => !i.fileId || value.some((f) => f.fileId === i.fileId)}
        others={picked.map((f) => ({ key: f.fileId, name: nameOf(f), status: 'In Files', onRemove: () => onChange(value.filter((v) => v.fileId !== f.fileId)) }))}
        onChange={(items) => {
          const held = items.filter((i) => i.fileId).map((i) => ({ fileId: i.fileId!, name: i.name }));
          const removed = uploads.current.filter((u) => !held.some((h) => h.fileId === u));
          uploads.current = held.map((h) => h.fileId);
          setUploadIds(uploads.current);
          const kept = value.filter((f) => !removed.includes(f.fileId));
          const next = many ? [...kept, ...held.filter((h) => !kept.some((f) => f.fileId === h.fileId))] : held.length ? held.slice(-1) : kept;
          if (next.length !== value.length || next.some((f, i) => f.fileId !== value[i]?.fileId)) onChange(next);
        }}
      />
      <EntityPicker
        source={source}
        multiple={many}
        showChosen={false}
        value={value.map((f) => f.fileId)}
        onChange={(ids) => onChange(ids.map((fid) => value.find((f) => f.fileId === fid) ?? { fileId: fid }))}
        addLabel={many ? 'Pick files from Files' : 'Pick a file from Files'}
        searchPlaceholder="Search files"
        testId={`${testId}-pick`}
      />
    </div>
  );
}
