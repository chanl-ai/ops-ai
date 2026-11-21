'use client';

import * as React from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { useSaveWorkingCopy } from '@/hooks/engine-queries';
import { useReloadToRead } from '@/hooks/use-reload-to-read';
import { baseOf, staleNote, staleSave } from '@/lib/save-base';
import type { DefinitionCheck, DefinitionView, EngineDefinition } from '@/lib/types/engine';

export type SaveState = 'saved' | 'unsaved' | 'saving' | 'failed' | 'stale';

const AUTOSAVE_MS = 1000;

/**
 * The workflow editor's working copy saves itself a second after the last change and never makes a version. Each save
 * names the copy the page read (`saveBase`). One refused because that copy is old is never sent again, even after the
 * person's own save from another tab: the canvas is one field, so a re-sent save would replace that tab's whole canvas
 * (the agent page re-sends because its saves merge field by field). `stale` says who saved and when, and nothing more
 * is sent until `reload`, which shows the newest copy and drops this page's unsaved change.
 *
 * A save that fails is not sent again until the definition changes or `retry` is pressed. `replacing` names an outdated
 * copy's digest (one made on an older version) the person chose to start over from: the server keeps another person's
 * outdated copy until a save names it, so the saves name it until the view holds a working copy again.
 */
export function useWorkingCopy(view: DefinitionView, enabled: boolean, replacing?: string | null) {
  const qc = useQueryClient();
  const save = useSaveWorkingCopy(view.workflowId);
  // The definition waiting to be saved; null once what is on screen is stored.
  const [edited, setEdited] = React.useState<EngineDefinition | null>(null);
  const [failed, setFailed] = React.useState<{ sent: string; message: string } | null>(null);
  const [stale, setStale] = React.useState<string | null>(null);
  const [checks, setChecks] = React.useState<DefinitionCheck[] | null>(view.workingCopy?.checks ?? null);
  const [savedAt, setSavedAt] = React.useState<string | null>(view.workingCopy?.updatedAt ?? null);
  // The editor is mounted again on a reload, so it opens on the copy just read.
  const [revision, setRevision] = React.useState(0);
  const editing = edited ? JSON.stringify(edited) : null;

  // Reload shows the newest copy: `reading` pauses autosave until `view` carries the digest that was read, then the
  // editor is mounted again on it. A failed read throws, so the refused save's notice stays and nothing is dropped.
  const readNewest = React.useCallback(async () => {
    const key = ['engine', 'definition', view.workflowId, 'latest'];
    await qc.refetchQueries({ queryKey: key }, { throwOnError: true });
    return qc.getQueriesData<DefinitionView>({ queryKey: key }).find(([, v]) => v)?.[1]?.saveBase.digest;
  }, [qc, view.workflowId]);
  const { reload, reading } = useReloadToRead(view.saveBase.digest, readNewest, () => {
    setEdited(null);
    setStale(null);
    setFailed(null);
    setChecks(null);
    setRevision((r) => r + 1);
  });

  const saveNow = () => {
    if (!edited || !editing) return;
    const sent = editing;
    save.mutate(
      { definition: edited, base: { ...baseOf(view.saveBase), ...(replacing && !view.workingCopy ? { replacesDigest: replacing } : {}) } },
      {
        onSuccess: (r) => {
          setChecks(r.workingCopy.checks);
          setSavedAt(r.workingCopy.updatedAt);
          setFailed(null);
          // A change made while this save was in flight stays waiting for the next one.
          setEdited((cur) => (cur && JSON.stringify(cur) === sent ? null : cur));
        },
        onError: (e) => {
          const refused = staleSave(e);
          if (refused) return setStale(staleNote(refused));
          setFailed({ sent, message: e instanceof Error ? e.message : 'The change was not saved' });
        },
      },
    );
  };

  React.useEffect(() => {
    if (!enabled || !editing || save.isPending || reading || stale || failed?.sent === editing) return;
    const t = setTimeout(saveNow, AUTOSAVE_MS);
    return () => clearTimeout(t);
    // Saves on a change, once the last save has settled and once a newer base has been read.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, enabled, save.isPending, reading, stale, failed, view.saveBase.digest]);

  const state: SaveState = stale ? 'stale' : save.isPending ? 'saving' : failed && failed.sent === editing ? 'failed' : editing ? 'unsaved' : 'saved';
  return {
    onChange: setEdited,
    saveNow,
    state,
    checks,
    savedAt,
    stale,
    error: failed?.message ?? null,
    retry: () => {
      setFailed(null);
      saveNow();
    },
    reload,
    reading,
    revision,
    /** True while something on screen is not stored, which the leave guard holds the page for. */
    unsaved: !!editing,
  };
}
