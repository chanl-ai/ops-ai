'use client';

import * as React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/lib/api';
import type { ReadRequestInput } from '@/lib/types/files';

export const ek = {
  byFile: (fileId: string) => ['extractions', 'file', fileId] as const,
  one: (id: string) => ['extractions', 'one', id] as const,
};

const running = (status: string | undefined) => status === 'queued' || status === 'running';

/** The file's extractions, newest first; polls while the newest is still running. */
export const useFileExtractions = (fileId: string) =>
  useQuery({
    queryKey: ek.byFile(fileId),
    queryFn: () => api.files.extractions.byFile(fileId),
    refetchInterval: (q) => (running(q.state.data?.data[0]?.status) ? 1500 : false),
  });

export interface ReadResult {
  runId: string;
  /** The run's status when the console stopped waiting: finished, or waiting at a Human Task for a person. */
  status: string;
  outcome: string | null;
}

const settled = (status: string) => ['succeeded', 'failed', 'cancelled', 'waiting'].includes(status);

/**
 * Reads the file: a read request on files-service raises the file's read event, which starts the system extract
 * workflow as the person; that run extracts, asks a person to check doubtful fields, and records Read as on the file.
 * Resolves once the run is finished or waiting for a person. One key per dialog opening, so a double click starts one.
 */
export function useStartExtraction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ fileId, input, key }: { fileId: string; input: ReadRequestInput; key: string }): Promise<ReadResult> => {
      let req = await api.files.readRequests.start(fileId, input, key);
      for (let i = 0; !req.runId && req.status !== 'unhandled' && i < 60; i++) {
        await new Promise((r) => setTimeout(r, 500));
        // The request is looked up by the key the service gave it, which is not the idempotency key.
        req = await api.files.readRequests.get(fileId, req.key);
      }
      if (req.status === 'unhandled') throw new Error('No live workflow reads files in this workspace. Publish the Extract from file workflow, then try again.');
      if (!req.runId) throw new Error('The read was requested but its run has not started yet. Look for it under Runs in a moment.');
      let run = await api.engine.run(req.runId);
      for (let i = 0; !settled(run.status) && i < 240; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        run = await api.engine.run(req.runId);
      }
      return { runId: req.runId, status: run.status, outcome: run.outcome ?? null };
    },
    onSuccess: (_, { fileId }) =>
      Promise.all([qc.invalidateQueries({ queryKey: ek.byFile(fileId) }), qc.invalidateQueries({ queryKey: ['files'] })]),
  });
}

/**
 * The file's bytes as a link the viewer can frame. files-service sends downloads as attachments, so a frame pointed at
 * a signed storage link would save the file instead of showing it; such a link's bytes are fetched once and shown from
 * memory. Each signed link issued is audited, so this asks for one per page visit.
 */
export function useFilePreviewUrl(fileId: string, enabled: boolean) {
  const link = useQuery({ queryKey: ['files', 'preview-link', fileId], queryFn: () => api.files.downloadUrl(fileId), enabled, staleTime: Infinity, gcTime: 0, retry: false });
  const [state, setState] = React.useState<{ url: string | null; error: string | null }>({ url: null, error: null });
  const signed = link.data?.url;
  React.useEffect(() => {
    if (!signed) return;
    let created: string | null = null;
    let live = true;
    // On the local backend the client already hands back a blob link to the bytes. That link is the cached query's, so
    // it is never revoked here: a remount (a resize across the phone breakpoint) reads it again from the cache.
    const bytes = signed.startsWith('blob:')
      ? Promise.resolve(signed)
      : fetch(signed)
          .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(`The file could not be read (${r.status}).`))))
          .then((b) => (created = URL.createObjectURL(b)));
    bytes.then((u) => live && setState({ url: u, error: null })).catch((e: Error) => live && setState({ url: null, error: e.message }));
    return () => {
      live = false;
      if (created) URL.revokeObjectURL(created);
    };
  }, [signed]);
  return { url: state.url, error: link.error ? (link.error as Error).message : state.error, loading: link.isLoading || (!!signed && !state.url && !state.error) };
}

/** Saves a person's values for a read's fields, one call per changed field, then reads the file's reads again. */
export function useCorrectFields(fileId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, changes }: { id: string; changes: { key: string; value: unknown; record?: number }[] }) => {
      for (const c of changes) await api.files.extractions.correct(id, c.key, c.value, c.record);
    },
    onSuccess: () => {
      // A correction on the newest read re-saves the file's data through a workflow a few seconds later.
      setTimeout(() => void qc.invalidateQueries({ queryKey: ['files'] }), 4000);
      return qc.invalidateQueries({ queryKey: ek.byFile(fileId) });
    },
  });
}
