"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { OptionSource } from "@/hooks/options-queries";
import { usePagedQuery } from "@/hooks/paged-query";
import { api } from "@/lib/api";
import type { ListParams } from "@/lib/types/query";
import type {
  DocumentTypeInput,
  DocumentTypeSampleInput,
  DocumentTypeTestRun,
  DocumentTypeVersionInput,
} from "@/lib/types/document-types";
import { teamKey, useTeamQuery } from "./team-query";

export const dtk = {
  list: ["document-types", "list"] as const,
  one: (id: string) => ["document-types", "one", id] as const,
  estimate: (id: string, version: number) =>
    ["document-types", "estimate", id, version] as const,
  test: (id: string, testId: string) =>
    ["document-types", "test", id, testId] as const,
  /** Tests started in this session, by version: the service lists no past runs, so the page remembers its own. */
  sessionTests: (id: string) =>
    ["document-types", "session-tests", id] as const,
};

/** One page of the team's types; the server searches, orders and counts. */
export const useDocumentTypes = (p: ListParams) =>
  usePagedQuery({
    queryKey: [...dtk.list, p],
    queryFn: () => api.files.documentTypes.list(p),
  });

/** Document types for a picker: searched on the server as typed, or named by id; a page number is the cursor. */
export const documentTypeOptions: OptionSource = {
  key: "document-type-options",
  fetch: async ({ search, cursor, limit = 25, ids }) => {
    const page = Number(cursor ?? 1);
    const res = await api.files.documentTypes.list(
      ids?.length
        ? { page: 1, pageSize: Math.min(ids.length, 50), ids }
        : { page, pageSize: limit, search: search || undefined },
    );
    return {
      data: res.data.map((t) => ({ id: t.id, label: t.name, hint: t.description })),
      nextCursor: !ids?.length && res.pagination.hasNext ? String(page + 1) : null,
    };
  },
};
export const useDocumentType = (id: string) =>
  useTeamQuery({
    queryKey: dtk.one(id),
    queryFn: () => api.files.documentTypes.get(id),
    enabled: !!id,
  });

/** Writes change the type's page and the list; samples also change what references their files. */
function useDocumentTypeWrite<A, R>(
  fn: (a: A) => Promise<R>,
  alsoFiles = false,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    // Not every `document-types` key: the session's test ids live in the cache and a refetch would forget them.
    onSuccess: () =>
      Promise.all([
        ...[
          dtk.list,
          ["document-types", "one"],
          ["document-types", "estimate"],
        ].map((queryKey) => qc.invalidateQueries({ queryKey })),
        ...(alsoFiles ? [qc.invalidateQueries({ queryKey: ["files"] })] : []),
      ]),
  });
}

export const useCreateDocumentType = () =>
  useDocumentTypeWrite((i: DocumentTypeInput) =>
    api.files.documentTypes.create(i),
  );
export const useAddDocumentTypeVersion = () =>
  useDocumentTypeWrite(
    ({ id, input }: { id: string; input: DocumentTypeVersionInput }) =>
      api.files.documentTypes.addVersion(id, input),
  );
export const useAddSample = () =>
  useDocumentTypeWrite(
    ({ id, input }: { id: string; input: DocumentTypeSampleInput }) =>
      api.files.documentTypes.addSample(id, input),
    true,
  );
export const useRemoveSample = () =>
  useDocumentTypeWrite(
    ({ id, sampleId }: { id: string; sampleId: string }) =>
      api.files.documentTypes.removeSample(id, sampleId),
    true,
  );

/** Read fresh each time the run dialog opens, since samples may have changed. */
export const useTestEstimate = (
  id: string,
  version: number,
  enabled: boolean,
) =>
  useTeamQuery({
    queryKey: dtk.estimate(id, version),
    queryFn: () => api.files.documentTypes.estimate(id, version),
    enabled: enabled && !!id && version > 0,
    staleTime: 0,
    gcTime: 0,
  });

/** The newest test started in this session for each version of a type. */
export function useSessionTests(id: string) {
  const qc = useQueryClient();
  return useTeamQuery({
    queryKey: dtk.sessionTests(id),
    // Nothing to fetch: a broad invalidation (a team switch) refetches it, which must keep the ids already held.
    queryFn: () => qc.getQueryData<Record<number, string>>(teamKey(dtk.sessionTests(id))) ?? {},
    initialData: {} as Record<number, string>,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

/** Starts a test and remembers it as the version's newest, so the Tests tab follows it. */
export function useStartTest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      api.files.documentTypes.startTest(id, version),
    onSuccess: (run) => {
      qc.setQueryData<Record<number, string>>(
        teamKey(dtk.sessionTests(run.typeId)),
        (prev) => ({ ...prev, [run.version]: run.id }),
      );
      qc.setQueryData(teamKey(dtk.test(run.typeId, run.id)), run);
    },
  });
}

const settled = (run?: DocumentTypeTestRun) =>
  run?.status === "done" || run?.status === "failed";

/** Polls every 2 seconds while the test is queued or running. */
export const useTestRun = (id: string, testId: string | undefined) =>
  useTeamQuery({
    queryKey: dtk.test(id, testId ?? ""),
    queryFn: () => api.files.documentTypes.test(id, testId!),
    enabled: !!testId,
    refetchInterval: (q) =>
      q.state.data && !settled(q.state.data) ? 2000 : false,
    staleTime: (q) => (settled(q.state.data) ? Infinity : 0),
  });
