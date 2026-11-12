import type {
  DocumentField,
  DocumentFieldType,
  DocumentType,
  DocumentTypeSample,
  DocumentTypeTestResult,
  DocumentTypeTestRun,
  DocumentTypeVersion,
  DocumentTypeVersionInput,
  ExpectedRecord,
  FieldComparison,
} from "@/lib/types/document-types";
import type { FileReference } from "@/lib/types/files";

import { ApiError } from "../../contract";
import type { FilesApi } from "../../files-contract";
import { id, notFound, respond } from "../runtime";
import { inTeam, teamOwner } from "../teams";
import { daysAgo, type FileSeed } from "./seed";

/** files-service tests at most this many samples per run, one model call each (two when a re-ask is needed). */
const MAX_TEST_SAMPLES = 20;
const ALIAS = "extract-default";
/** The mock's price for one extraction call, in dollars, so the estimate shows a cost. */
const PRICE_PER_CALL = 0.0042;
/** A queued test starts running after this long and finishes after the second; read on each poll, as scans are. */
const QUEUED_MS = 1500;
const DONE_MS = 6000;
const FIELD_TYPES: DocumentFieldType[] = [
  "text",
  "number",
  "money",
  "date",
  "enum",
];
const ID = /^[a-z][a-z0-9_]{2,63}$/;
const KEY = /^[a-z0-9_]+$/;

const LEVY = "levy_notice";
const levyRef = (sampleId: string): Omit<FileReference, "addedAt"> => ({
  type: "test_set",
  id: sampleId,
  name: "Levy notice",
  href: `/document-types/${LEVY}?tab=samples`,
});

/** Levy notices in Retail Banking's files: two are the seeded type's samples, the third is free to add as one. */
export const DOCUMENT_TYPE_FILES: FileSeed[] = [
  {
    id: "file_levy_on_0914",
    name: "levy-notice-ontario-0914.pdf",
    purpose: "document_type_sample",
    team: "Retail Banking",
    by: "Mailbox intake",
    daysAgo: 34,
    sizeKb: 212,
    refs: [levyRef("smp_levy_on")],
  },
  {
    id: "file_levy_bc_1002",
    name: "levy-notice-bc-1002.pdf",
    purpose: "document_type_sample",
    team: "Retail Banking",
    by: "Mailbox intake",
    daysAgo: 16,
    sizeKb: 148,
    refs: [levyRef("smp_levy_bc")],
  },
  {
    id: "file_levy_ab_1011",
    name: "levy-notice-alberta-1011.pdf",
    purpose: "document_type_sample",
    team: "Retail Banking",
    by: "Mailbox intake",
    daysAgo: 7,
    sizeKb: 176,
  },
];

const V1_FIELDS: DocumentField[] = [
  { key: "name", label: "Account holder", type: "text", required: true },
  { key: "address", label: "Address", type: "text" },
  {
    key: "ssn_last4",
    label: "SIN or SSN, last 4",
    type: "text",
    alwaysReview: true,
  },
  { key: "amount", label: "Amount levied", type: "money", required: true },
  { key: "court", label: "Court", type: "text" },
  { key: "case_no", label: "Case number", type: "text", required: true },
];
const V2_FIELDS: DocumentField[] = [
  ...V1_FIELDS.slice(0, 4).map((f) =>
    f.key === "amount" ? { ...f, reviewBelow: 0.9 } : f,
  ),
  {
    key: "currency",
    label: "Currency",
    type: "enum",
    required: true,
    options: ["CAD", "USD", "EUR", "GBP"],
  },
  ...V1_FIELDS.slice(4),
];

type StoredType = Omit<DocumentType, "canEdit" | "latestVersion">;
interface StoredTest {
  run: DocumentTypeTestRun;
  startAt: number;
  doneAt: number;
}

export interface DocumentTypesDeps {
  me: string;
  /** The name of a file in the caller's team that can be read now; throws when it cannot. */
  sampleFile: (fileId: string) => string;
  /** Records the sample on the file, so Files keeps it while the sample names it. */
  reference: (fileId: string, ref: Omit<FileReference, "addedAt">) => void;
  unreference: (fileId: string, refId: string) => void;
}

const num = (v: unknown) => Number(String(v).replace(/[^0-9.-]/g, ""));
const fold = (v: unknown) =>
  String(v)
    .toLowerCase()
    .replace(/[‘’“”]/g, "'")
    .replace(/\s+/g, " ")
    .trim();
/** Numbers and money compare by value, so "12,850.00" read for an expected 12850 is a match; text compares folded. */
const matches = (f: DocumentField, expected: unknown, got: unknown) =>
  got == null
    ? expected == null
    : f.type === "number" || f.type === "money"
      ? num(expected) === num(got)
      : fold(expected) === fold(got);

/** What the mock extraction reads: the expected value, except for a few deliberate misreads so results show misses. */
function read(
  f: DocumentField,
  value: string | number | null,
  sample: number,
  record: number,
): string | number | null {
  if (value == null) return null;
  if (f.key === "ssn_last4" && record === 1)
    return String(value).replace(/8/g, "3");
  if (f.key === "case_no" && sample % 2 === 1)
    return String(value).slice(0, -1);
  if (f.type === "money")
    return num(value).toLocaleString("en-CA", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  return value;
}

function checkFields(input: DocumentTypeVersionInput) {
  if (!Array.isArray(input.fields) || !input.fields.length)
    throw new ApiError("Add at least one field.", 400);
  const seen = new Set<string>();
  for (const f of input.fields) {
    if (!f.key || !KEY.test(f.key))
      throw new ApiError(
        `Field keys are lowercase letters, digits and underscores; “${f.key}” is not.`,
        400,
      );
    if (!FIELD_TYPES.includes(f.type))
      throw new ApiError(`Field ${f.key} has an unknown type.`, 400);
    if (seen.has(f.key))
      throw new ApiError(`Field ${f.key} is named twice.`, 400);
    seen.add(f.key);
  }
  if (
    input.reviewBelow != null &&
    (input.reviewBelow < 0 || input.reviewBelow > 1)
  )
    throw new ApiError("Review below is a confidence between 0 and 1.", 400);
}

export function createDocumentTypesMock(
  deps: DocumentTypesDeps,
): FilesApi["documentTypes"] {
  const { me } = deps;
  const version = (
    n: number,
    fields: DocumentField[],
    note: string | null,
    by: string,
    at: string,
  ): DocumentTypeVersion => ({
    version: n,
    fields,
    many: true,
    reviewBelow: 0.8,
    note,
    createdBy: by,
    createdAt: at,
  });
  const types: StoredType[] = [
    {
      id: LEVY,
      name: "Levy notice",
      description:
        "A court or tax authority orders the bank to hold or pay out an account holder’s funds.",
      team: "Retail Banking",
      createdBy: "Priya Shah",
      createdAt: daysAgo(30),
      versions: [
        version(
          2,
          V2_FIELDS,
          "Added currency; low-confidence amounts go to review",
          "Priya Shah",
          daysAgo(9),
        ),
        version(1, V1_FIELDS, null, "Priya Shah", daysAgo(30)),
      ],
      samples: [
        {
          id: "smp_levy_on",
          fileId: "file_levy_on_0914",
          name: "levy-notice-ontario-0914.pdf",
          expected: [
            {
              name: "Maria Delgado",
              address: "41 Wexford Ave, Toronto ON",
              ssn_last4: "4417",
              amount: 12850,
              currency: "CAD",
              court: "Ontario Superior Court of Justice",
              case_no: "CV-26-00071432",
            },
            {
              name: "Daniel Delgado",
              address: "41 Wexford Ave, Toronto ON",
              ssn_last4: "9082",
              amount: 12850,
              currency: "CAD",
              court: "Ontario Superior Court of Justice",
              case_no: "CV-26-00071432",
            },
          ],
          addedBy: "Priya Shah",
          addedAt: daysAgo(29),
        },
        {
          id: "smp_levy_bc",
          fileId: "file_levy_bc_1002",
          name: "levy-notice-bc-1002.pdf",
          expected: [
            {
              name: "Kevin Nguyen",
              address: "2210 Oak St, Vancouver BC",
              ssn_last4: "3308",
              amount: 3250.75,
              currency: "CAD",
              court: "Supreme Court of British Columbia",
              case_no: "S-2610447",
            },
          ],
          addedBy: "Priya Shah",
          addedAt: daysAgo(15),
        },
      ],
    },
  ];
  const tests = new Map<string, StoredTest>();

  const view = (t: StoredType): DocumentType => ({
    ...t,
    latestVersion: t.versions[0].version,
    canEdit: true,
  });
  const find = (typeId: string) => {
    const t = types.find((x) => x.id === typeId);
    return t && inTeam(t.team) ? t : notFound("Document type");
  };
  const versionOf = (t: StoredType, n: number) =>
    t.versions.find((v) => v.version === n) ?? notFound(`Version ${n}`);

  const result = (
    t: StoredType,
    v: DocumentTypeVersion,
  ): DocumentTypeTestResult => {
    const rows = t.samples.slice(0, MAX_TEST_SAMPLES).map((s, si) => {
      const wanted = Array.isArray(s.expected) ? s.expected : [s.expected];
      const fields: Record<string, FieldComparison[]> = {};
      wanted.forEach((want, ri) => {
        for (const f of v.fields) {
          if (!(f.key in want)) continue;
          const got = read(f, want[f.key], si, ri);
          (fields[f.key] ??= []).push({
            expected: want[f.key],
            got,
            match: matches(f, want[f.key], got),
          });
        }
      });
      return {
        sampleId: s.id,
        name: s.name,
        extractionId: id("ext"),
        status: "done",
        fields,
      };
    });
    const per = Object.fromEntries(
      v.fields.map((f) => {
        const seen = rows.flatMap((r) => r.fields[f.key] ?? []);
        const hit = seen.filter((c) => c.match).length;
        return [
          f.key,
          {
            matches: hit,
            misses: seen.length - hit,
            accuracy: seen.length
              ? Math.round((hit / seen.length) * 10_000) / 10_000
              : null,
          },
        ];
      }),
    );
    const total = Object.values(per).reduce(
      (n, p) => n + p.matches + p.misses,
      0,
    );
    const hits = Object.values(per).reduce((n, p) => n + p.matches, 0);
    return {
      samples: rows,
      fields: per,
      accuracy: total ? Math.round((hits / total) * 10_000) / 10_000 : null,
    };
  };

  /** Moves a test along by the clock on each read, so the page's poll sees queued, running, then done. */
  const settle = (st: StoredTest) => {
    const now = Date.now();
    if (st.run.status === "queued" && now >= st.startAt)
      st.run.status = "running";
    if (st.run.status === "running" && now >= st.doneAt) {
      const t = types.find((x) => x.id === st.run.typeId);
      const v = t?.versions.find((x) => x.version === st.run.version);
      if (t && v) {
        st.run.status = "done";
        st.run.result = result(t, v);
      } else {
        st.run.status = "failed";
        st.run.error = "The document type or version no longer exists.";
      }
    }
    return st.run;
  };

  return {
    list: () =>
      respond((m) => ({
        items:
          m === "empty"
            ? []
            : types
                .filter((t) => inTeam(t.team))
                .map((t) => ({
                  id: t.id,
                  name: t.name,
                  description: t.description,
                  latestVersion: t.versions[0].version,
                })),
        canCreate: true,
      })),

    get: (typeId) => respond(() => view(find(typeId))),

    create: (input) =>
      respond(() => {
        const name = input.name?.trim();
        if (!name) throw new ApiError("Name the document type.", 400);
        const typeId = input.id?.trim() || id("dt");
        if (input.id && !ID.test(typeId))
          throw new ApiError(
            "The id is 3 to 64 lowercase letters, digits and underscores, starting with a letter.",
            400,
          );
        if (types.some((t) => t.id === typeId))
          throw new ApiError(`The id ${typeId} is taken.`, 409);
        const team = teamOwner() ?? "Retail Banking";
        if (
          types.some(
            (t) =>
              t.team === team && t.name.toLowerCase() === name.toLowerCase(),
          )
        )
          throw new ApiError(
            `${team} already has a document type named ${name}.`,
            409,
          );
        checkFields(input);
        const at = new Date().toISOString();
        const t: StoredType = {
          id: typeId,
          name,
          description: input.description?.trim() || null,
          team,
          createdBy: me,
          createdAt: at,
          versions: [
            {
              version: 1,
              fields: input.fields,
              many: !!input.many,
              reviewBelow: input.reviewBelow ?? null,
              note: input.note?.trim() || null,
              createdBy: me,
              createdAt: at,
            },
          ],
          samples: [],
        };
        types.unshift(t);
        return view(t);
      }),

    addVersion: (typeId, input) =>
      respond(() => {
        const t = find(typeId);
        checkFields(input);
        const v: DocumentTypeVersion = {
          version: t.versions[0].version + 1,
          fields: input.fields,
          many: !!input.many,
          reviewBelow: input.reviewBelow ?? null,
          note: input.note?.trim() || null,
          createdBy: me,
          createdAt: new Date().toISOString(),
        };
        t.versions.unshift(v);
        return v;
      }),

    addSample: (typeId, input) =>
      respond(() => {
        const t = find(typeId);
        const latest = t.versions[0];
        const records: unknown[] =
          latest.many && Array.isArray(input.expected)
            ? input.expected
            : [input.expected];
        if (
          (latest.many && !Array.isArray(input.expected)) ||
          !records.every((r) => r && typeof r === "object" && !Array.isArray(r))
        )
          throw new ApiError(
            "Give the values for each record the file holds.",
            400,
          );
        const keys = new Set(latest.fields.map((f) => f.key));
        const unknown = [
          ...new Set(records.flatMap((r) => Object.keys(r as ExpectedRecord))),
        ]
          .filter((k) => !keys.has(k))
          .sort();
        if (unknown.length)
          throw new ApiError(
            `Version ${latest.version} has no field named ${unknown.join(", ")}.`,
            400,
          );
        const name = deps.sampleFile(input.fileId);
        const sample: DocumentTypeSample = {
          id: id("smp"),
          fileId: input.fileId,
          name,
          expected: input.expected,
          addedBy: me,
          addedAt: new Date().toISOString(),
        };
        deps.reference(input.fileId, {
          type: "test_set",
          id: sample.id,
          name: t.name,
          href: `/document-types/${t.id}?tab=samples`,
        });
        t.samples.push(sample);
        return sample;
      }),

    removeSample: (typeId, sampleId) =>
      respond(() => {
        const t = find(typeId);
        const gone =
          t.samples.find((x) => x.id === sampleId) ?? notFound("Sample");
        t.samples.splice(t.samples.indexOf(gone), 1);
        deps.unreference(gone.fileId, gone.id);
      }),

    estimate: (typeId, n) =>
      respond(() => {
        const t = find(typeId);
        versionOf(t, n);
        const samples = Math.min(t.samples.length, MAX_TEST_SAMPLES);
        return {
          samples,
          calls: samples,
          maxCalls: samples * 2,
          alias: ALIAS,
          capped: MAX_TEST_SAMPLES,
          estimatedCost: (PRICE_PER_CALL * samples).toFixed(4),
          maxCost: (PRICE_PER_CALL * samples * 2).toFixed(4),
        };
      }),

    startTest: (typeId, n) =>
      respond(() => {
        const t = find(typeId);
        versionOf(t, n);
        if (!t.samples.length)
          throw new ApiError("Add a sample before testing a version.", 400);
        const now = Date.now();
        const run: DocumentTypeTestRun = {
          id: id("dtt"),
          typeId,
          version: n,
          status: "queued",
          samples: Math.min(t.samples.length, MAX_TEST_SAMPLES),
          askedBy: me,
          askedAt: new Date(now).toISOString(),
        };
        tests.set(run.id, {
          run,
          startAt: now + QUEUED_MS,
          doneAt: now + DONE_MS,
        });
        return run;
      }),

    test: (typeId, testId) =>
      respond(() => {
        find(typeId);
        const st = tests.get(testId);
        if (!st || st.run.typeId !== typeId) return notFound("Test");
        return settle(st);
      }),
  };
}
