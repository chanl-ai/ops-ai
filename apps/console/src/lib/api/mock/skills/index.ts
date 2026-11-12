import type { Agent, BulkResult, Review, ReviewDecisionInput, Tool } from '@/lib/types/domain';
import type { EvalCheckResult } from '@/lib/types/evals';
import type {
  AgentSkillPin,
  AgentSkills,
  GeneratedSkill,
  LoadedSkill,
  Skill,
  SkillCandidate,
  SkillCandidates,
  SkillCandidateScope,
  SkillCitation,
  SkillContent,
  SkillDetail,
  SkillDraftForCheck,
  SkillEditClass,
  SkillImpact,
  SkillImportPreview,
  SkillOrigin,
  SkillPublishCheck,
  SkillPublishRequest,
  SkillResource,
  SkillRuntimeLimits,
  SkillSectionKey,
  SkillStatus,
  SkillTestCase,
  SkillTestCaseInput,
  SkillTestResult,
  SkillTestRun,
  SkillToolRef,
  SkillUsage,
  SkillVersion,
  SkillVersionState,
  SkillView,
  SkillWarning,
  SkillLoading,
} from '@/lib/types/skills';
import type { SearchHit } from '@/lib/types/search';

import { plural } from '@/lib/format';

import type { CasesApi } from '../../cases-contract';
import type { ChatApi } from '../../chat-contract';
import { ApiError, type OpsApi } from '../../contract';
import type { SkillsApi } from '../../skills-contract';
import type { FileLinks } from '../files';
import { auditSink } from '../governance';
import { pageOptions } from '../../options';
import { field, id, list, mode, notFound, respond } from '../runtime';
import { guardTeam, inTeam, teamOwner } from '../teams';
import { packFor, type PastWorkItem, rewrite, splitSections, topicOf } from './generate';
import { ALWAYS_ON_SEEDS, ARCHIVED_CASES, DOCUMENTS, SKILL_SEEDS, TEMPLATES } from './seed';
import type { MockAgent } from '../fixtures';

export interface SkillsDeps {
  /** Agent rows with `usedIn`; read at request time. */
  agents: () => MockAgent[];
  tools: () => Tool[];
  kbNames: () => string[];
  /** The shared review list; skill publish requests are added to it. */
  reviews: () => Review[];
  /** Saves a new agent version; attaching, detaching and moving a pin change the agent. */
  bumpAgent: (agentId: string, note: string) => void;
  files: FileLinks;
  cases: CasesApi;
  chat: ChatApi;
  teams: string[];
  me: string;
}

const LIMITS: SkillRuntimeLimits = { maxPerTurn: 2, maxAttached: 12, tokenBudget: 6000, useWhenMaxChars: 1024 };
const DAY = 86_400_000;
const ago = (days: number) => new Date(Date.now() - days * DAY).toISOString();
const ymd = (iso: string) => iso.slice(0, 10);
const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const slugify = (sk: string) => sk.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 64);
const tokensOf = (c: Pick<StoredContent, 'instructions' | 'guardrails'>) => Math.round((c.instructions.length + c.guardrails.join(' ').length) / 4);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const isOpen = (r: Review) => r.status === 'pending' || r.status === 'in_review';
const STOP = new Set(['about', 'after', 'another', 'asks', 'customer', 'their', 'there', 'which', 'would', 'should', 'request', 'requests', 'when', 'where', 'other', 'such', 'that', 'this', 'with', 'from', 'says', 'they', 'cannot']);

function hash(key: string) {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) h = Math.imul(h ^ key.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10_000) / 10_000;
}

interface StoredContent {
  name: string;
  slug: string;
  useWhen: string;
  loading: SkillLoading;
  instructions: string;
  toolIds: string[];
  knowledgeBases: string[];
  guardrails: string[];
  resources: SkillResource[];
}

interface StoredVersion {
  version: number;
  state: SkillVersionState;
  editClass: SkillEditClass;
  note: string;
  changes: string[];
  savedBy: string;
  savedAt: string;
  content: StoredContent;
  reviewId?: string;
  publishedAt?: string;
  publishedBy?: string;
}

interface Stored {
  id: string;
  ownerTeam: string;
  origin: SkillOrigin;
  provenance: { detail: string; citations: SkillCitation[] };
  /** Newest first. */
  versions: StoredVersion[];
  tests: SkillTestCase[];
  runs: SkillTestRun[];
  matchTerms: string[];
  deprecated?: { by: string; at: string; reason: string };
  targetAgentIds: string[];
}

interface Pin {
  agentId: string;
  skillId: string;
  version: number;
  loads7d: number;
  share7d: number;
  attachedAt: string;
  attachedBy: string;
}

/**
 * Skills over the mock's agents, tools and knowledge bases. Publish requests are `skill_publish` reviews in the shared
 * queue (`wrapReviews` decides them), and pins live here and change the agent's version.
 */
export function createSkillsMock(deps: SkillsDeps) {
  const { me } = deps;
  const skills: Stored[] = [];
  const pins: Pin[] = [];
  const toolById = (tid: string) => deps.tools().find((t) => t.id === tid);
  const toolIdOf = (name: string) => deps.tools().find((t) => t.name === name)?.id;
  const ref = (tid: string): SkillToolRef | null => {
    const t = toolById(tid);
    return t ? { toolId: t.id, name: t.name, module: t.module ?? t.system, system: t.system, access: t.access } : null;
  };
  const refs = (tids: string[]) => tids.map(ref).filter((x): x is SkillToolRef => !!x);
  const agentOf = (aid: string) => deps.agents().find((a) => a.id === aid);

  // ── Seed ──
  let seq = 3100;
  for (const sk of [...SKILL_SEEDS, ...ALWAYS_ON_SEEDS]) {
    const base: StoredContent = {
      name: sk.name,
      slug: sk.slug,
      useWhen: sk.useWhen,
      loading: sk.loading ?? 'on_match',
      instructions: sk.instructions,
      toolIds: sk.tools.map(toolIdOf).filter((x): x is string => !!x),
      knowledgeBases: sk.knowledgeBases,
      guardrails: sk.guardrails,
      resources: [
        ...(sk.templates ?? []).map((t, i): SkillResource => ({ id: `res_${sk.id}_t${i}`, kind: 'template', name: t.name, body: t.body, addedAt: ago(sk.versions[0].daysAgo), addedBy: sk.versions[0].by })),
        ...(sk.files ?? []).map((f, i): SkillResource => ({ id: `res_${sk.id}_f${i}`, kind: 'file', name: f.name, description: f.description, size: f.sizeKb * 1024, addedAt: ago(sk.versions[0].daysAgo), addedBy: sk.versions[0].by })),
      ],
    };
    const stored: Stored = {
      id: sk.id,
      ownerTeam: sk.ownerTeam,
      origin: sk.origin,
      provenance: { detail: sk.provenance, citations: sk.citations.map((c, i) => ({ ...c, id: `cit_${sk.id}_${i}` })) },
      versions: [...sk.versions]
        .sort((a, b) => b.version - a.version)
        .map((v) => ({
          version: v.version,
          state: v.state,
          editClass: v.editClass,
          note: v.note,
          changes: v.changes,
          savedBy: v.by,
          savedAt: ago(v.daysAgo),
          publishedAt: ['published', 'superseded', 'deprecated'].includes(v.state) ? ago(v.daysAgo - 0.5) : undefined,
          publishedBy: ['published', 'superseded', 'deprecated'].includes(v.state) ? (v.by === 'Priya Shah' ? 'Maya Okafor' : 'Priya Shah') : undefined,
          content: {
            ...structuredClone(base),
            instructions: v.instructions ?? base.instructions,
            useWhen: v.useWhen ?? base.useWhen,
            toolIds: v.tools ? v.tools.map(toolIdOf).filter((x): x is string => !!x) : base.toolIds,
            knowledgeBases: v.knowledgeBases ?? base.knowledgeBases,
            guardrails: v.guardrails ?? base.guardrails,
          },
        })),
      tests: sk.tests.map((t, i) => ({ id: `stc_${sk.id}_${i}`, name: t.name, input: t.input, checks: t.checks, source: t.source, sourceRef: t.sourceRef, createdAt: ago(sk.versions[0].daysAgo), createdBy: sk.versions[0].by, lastOutcome: null })),
      runs: [],
      matchTerms: sk.matchTerms,
      deprecated: sk.deprecated && { by: sk.deprecated.by, at: ago(sk.deprecated.daysAgo), reason: sk.deprecated.reason },
      targetAgentIds: sk.pins.map((p) => p.agentId),
    };
    skills.push(stored);
    for (const v of sk.versions.filter((x) => x.run)) {
      const sv = stored.versions.find((x) => x.version === v.version)!;
      const run = evaluate(stored, sv.content, stored.tests, v.run!.failing ?? []);
      run.ranAt = ago(v.run!.daysAgo);
      run.ranBy = v.by;
      run.version = v.version;
      stored.runs.unshift(run);
    }
    stored.runs.sort((a, b) => b.ranAt.localeCompare(a.ranAt));
    markOutcomes(stored);
    for (const p of sk.pins) pins.push({ agentId: p.agentId, skillId: sk.id, version: p.version, loads7d: p.loads7d, share7d: p.share7d, attachedAt: ago(p.daysAgo), attachedBy: p.by });
  }

  function markOutcomes(sk: Stored) {
    const latest = sk.runs.find((r) => r.version === sk.versions[0].version) ?? sk.runs[0];
    for (const t of sk.tests) t.lastOutcome = latest?.results.find((r) => r.caseId === t.id)?.status ?? null;
  }

  // ── Runtime matching ──
  /** Seeded skills carry curated terms; others match on the long words of their name and use-when line. */
  function termsOf(sk: Pick<Stored, 'matchTerms'> | null, content: Pick<StoredContent, 'useWhen' | 'name'>) {
    if (sk?.matchTerms.length) return sk.matchTerms;
    const words = `${content.name} ${content.useWhen}`
      .toLowerCase()
      .replace(/^use when /, '')
      .split(/[^a-z’']+/)
      .filter((w) => w.length > 5 && !STOP.has(w));
    return [...new Set(words)];
  }
  function matchOf(terms: string[], text: string) {
    const t = text.toLowerCase();
    return terms.filter((x) => t.includes(x.toLowerCase()));
  }

  function evaluate(sk: Stored | null, content: StoredContent, tests: Pick<SkillTestCase, 'id' | 'name' | 'input' | 'checks'>[], forceFail: string[] = []): SkillTestRun {
    const toolNames = content.toolIds.map((t) => toolById(t)?.name).filter(Boolean) as string[];
    const text = `${content.instructions}\n${content.guardrails.join('\n')}\n${content.resources.map((r) => r.body ?? '').join('\n')}`.toLowerCase();
    const terms = termsOf(sk, content);
    const results: SkillTestResult[] = tests.map((t, i) => {
      const matched = matchOf(terms, t.input);
      // An always-on skill is in every turn, so every test input runs with it.
      const loaded = content.loading === 'always' || matched.length > 0;
      const checks: EvalCheckResult[] = t.checks.map((c) => {
        const label = c.type === 'calls_tool' ? `Calls ${c.tool}` : c.type === 'not_calls_tool' ? `Does not call ${c.tool}` : c.type === 'cites' ? `Cites ${c.source}${c.section ? ` ${c.section}` : ''}` : c.type === 'reply_contains' ? `Says “${c.text}”` : c.type === 'reply_not_contains' ? `Never says “${c.text}”` : 'Check';
        if (!loaded) return { label, status: 'fail', detail: 'The skill was not chosen for this input.' };
        if (c.type === 'calls_tool' && !toolNames.includes(c.tool ?? '')) return { label, status: 'fail', detail: `${c.tool} is not one of the skill’s tools.` };
        if (c.type === 'cites' && !content.knowledgeBases.includes(c.source ?? '')) return { label, status: 'fail', detail: `${c.source} is not one of the skill’s knowledge bases.` };
        if (c.type === 'reply_contains' && !text.includes((c.text ?? '').toLowerCase())) return { label, status: 'fail', detail: `Nothing in the skill leads to “${c.text}”.` };
        return { label, status: 'pass' };
      });
      const forced = forceFail.includes(t.name);
      if (forced) checks[checks.length - 1] = { ...checks[checks.length - 1], status: 'fail', detail: 'The reply did not meet this check.' };
      const failed = checks.find((c) => c.status === 'fail');
      return {
        caseId: t.id,
        caseName: t.name,
        status: failed ? 'fail' : 'pass',
        checks,
        failure: failed ? `${failed.label}: ${failed.detail}` : undefined,
        reply: loaded ? `Loaded ${content.name}. ${splitSections(content.instructions).steps.split('\n')[0]?.replace(/^\d+\.\s*/, '') ?? ''}` : 'Answered without the skill.',
        skillLoaded: loaded,
        toolsCalled: loaded ? t.checks.filter((c) => c.type === 'calls_tool' && toolNames.includes(c.tool ?? '')).map((c) => c.tool!) : [],
        latencyMs: 900 + Math.round(hash(`${t.input}:${i}`) * 2200),
      };
    });
    return { id: id('skr'), version: 0, ranAt: new Date().toISOString(), ranBy: me, passed: results.filter((r) => r.status === 'pass').length, total: results.length, results };
  }

  // ── Read models ──
  const newest = (sk: Stored) => sk.versions[0];
  const published = (sk: Stored) => sk.versions.find((v) => v.state === 'published') ?? (sk.deprecated ? sk.versions.find((v) => v.state === 'deprecated') : undefined);
  const openReview = (sk: Stored) => deps.reviews().find((r) => r.kind === 'skill_publish' && isOpen(r) && r.skillPublish?.skillId === sk.id);
  const livePins = (sk: Stored) => pins.filter((p) => p.skillId === sk.id && agentOf(p.agentId));
  const statusOf = (sk: Stored): SkillStatus => (sk.deprecated ? 'deprecated' : openReview(sk) ? 'in_review' : published(sk) ? 'published' : 'draft');
  const runFor = (sk: Stored, version: number) => sk.runs.find((r) => r.version === version);
  const content = (sk: Stored, c: StoredContent): SkillContent => ({ name: c.name, slug: c.slug, useWhen: c.useWhen, loading: c.loading, instructions: c.instructions, tools: refs(c.toolIds), knowledgeBases: c.knowledgeBases, guardrails: c.guardrails, resources: c.resources.map((r) => (r.fileId ? { ...r, blocked: deps.files.state(r.fileId)?.blocked } : r)) });

  const row = (sk: Stored): Skill => {
    const n = newest(sk);
    const pub = published(sk);
    const ps = livePins(sk);
    const run = runFor(sk, n.version) ?? sk.runs[0];
    const review = openReview(sk);
    return {
      id: sk.id,
      name: n.content.name,
      slug: n.content.slug,
      useWhen: n.content.useWhen,
      loading: n.content.loading,
      ownerTeam: sk.ownerTeam,
      status: statusOf(sk),
      version: n.version,
      publishedVersion: pub?.version ?? null,
      draftVersion: n.state === 'draft' || n.state === 'in_review' ? n.version : null,
      usedBy: ps.length,
      liveAgents: ps.filter((p) => agentOf(p.agentId)?.availability === 'published').length,
      toolCount: n.content.toolIds.length,
      kbCount: n.content.knowledgeBases.length,
      lastEvalPassRate: run ? run.passed / Math.max(1, run.total) : null,
      tokens: tokensOf(n.content),
      updatedAt: n.savedAt,
      updatedBy: n.savedBy,
      origin: sk.origin,
      pendingReviewId: review?.id,
    };
  };

  const publishCheck = (sk: Stored): SkillPublishCheck => {
    const n = newest(sk);
    const blockers: string[] = [];
    const ec = editClassOf(sk, n.content);
    if (sk.deprecated) blockers.push('The skill is deprecated.');
    else if (n.state === 'in_review') blockers.push(`v${n.version} is already waiting in Reviews.`);
    else if (n.state !== 'draft') blockers.push(`Nothing to publish: v${n.version} is ${n.state}. Edit the skill to open a draft.`);
    else {
      if (!sk.tests.length) blockers.push('Add at least one test case.');
      else if (!runFor(sk, n.version)) blockers.push(`Run the tests on v${n.version}.`);
      if (!n.content.instructions.trim()) blockers.push('Write the instructions.');
    }
    return { canRequest: !blockers.length, blockers, editClass: ec, approversNeeded: ec === 're_approval' ? 2 : 1 };
  };

  /** The class of the newest version against what is published: tools, knowledge or guardrails need re-approval. */
  function editClassOf(sk: Stored, c: StoredContent): SkillEditClass {
    const pub = published(sk);
    if (!pub || pub === newest(sk)) return newest(sk).editClass;
    const same = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
    if (!same(pub.content.toolIds, c.toolIds) || !same(pub.content.knowledgeBases, c.knowledgeBases) || !same(pub.content.guardrails, c.guardrails) || pub.content.resources.length !== c.resources.length) return 're_approval';
    if (pub.content.instructions !== c.instructions || pub.content.useWhen !== c.useWhen || pub.content.name !== c.name) return 're_test';
    return 'free';
  }

  const usageOf = (sk: Stored): SkillUsage[] => {
    const pub = published(sk);
    return livePins(sk).map((p) => {
      const a = agentOf(p.agentId)!;
      const missing = pub ? missingFor(a, pub.content) : [];
      const upgradeAvailable = !!pub && !sk.deprecated && pub.version > p.version;
      return {
        agentId: a.id,
        agentName: a.name,
        agentTeamId: a.teamId,
        agentAvailability: a.availability,
        pinnedVersion: p.version,
        latestPublished: pub?.version ?? null,
        upgradeAvailable,
        upgradeBlocked: upgradeAvailable && missing.length ? `v${pub!.version} needs ${missing.join(', ')}, which ${a.name} does not hold.` : undefined,
        loads7d: p.loads7d,
        share7d: p.share7d,
        lastLoadedAt: p.loads7d ? new Date(Date.now() - (1 + hash(`${sk.id}:${a.id}`) * 90) * 60_000).toISOString() : null,
        attachedAt: p.attachedAt,
        attachedBy: p.attachedBy,
      };
    });
  };

  const activityOf = (sk: Stored) => {
    const ps = livePins(sk);
    const agents = ps.map((p) => agentOf(p.agentId)!.name);
    const loadsPerDay = Array.from({ length: 14 }, (_, i) => {
      const date = ymd(ago(13 - i));
      const counts = Object.fromEntries(ps.map((p) => [agentOf(p.agentId)!.name, Math.max(0, Math.round((p.loads7d / 7) * (0.6 + hash(`${sk.id}:${p.agentId}:${i}`) * 0.8) * (new Date(date).getUTCDay() % 6 === 0 ? 0.35 : 1)))]));
      return { date, counts, total: Object.values(counts).reduce((n, x) => n + x, 0) };
    });
    const total = loadsPerDay.reduce((n, d) => n + d.total, 0);
    return {
      agents,
      loadsPerDay,
      loads30d: Math.round(total * 2.1),
      successRate: total ? 0.86 + hash(`${sk.id}:ok`) * 0.11 : null,
      samples: total
        ? sk.tests.slice(0, 5).map((t, i) => ({
            id: `trc_${sk.id}_${i}`,
            at: new Date(Date.now() - (i * 3 + 1) * 3_600_000 * (1 + hash(t.id))).toISOString(),
            agentName: agents[i % agents.length],
            version: ps[i % ps.length].version,
            input: t.input,
            outcome: (i === 3 ? 'handed_off' : 'completed') as 'handed_off' | 'completed',
            toolCalls: t.checks.filter((c) => c.type === 'calls_tool').map((c) => c.tool!),
            tookMs: 1400 + Math.round(hash(`${t.id}:ms`) * 2600),
          }))
        : [],
    };
  };

  const version = (sk: Stored, v: StoredVersion): SkillVersion => {
    const run = runFor(sk, v.version);
    return { version: v.version, state: v.state, editClass: v.editClass, note: v.note, changes: v.changes, savedBy: v.savedBy, savedAt: v.savedAt, content: content(sk, v.content), tokens: tokensOf(v.content), reviewId: v.reviewId, publishedAt: v.publishedAt, publishedBy: v.publishedBy, testRun: run ? { runId: run.id, version: run.version, ranAt: run.ranAt, passed: run.passed, total: run.total } : null };
  };

  const detail = (sk: Stored): SkillDetail => {
    const review = openReview(sk);
    return {
      ...row(sk),
      content: content(sk, newest(sk).content),
      versions: sk.versions.map((v) => version(sk, v)),
      tests: sk.tests,
      runs: sk.runs,
      usage: usageOf(sk),
      activity: activityOf(sk),
      provenance: { origin: sk.origin, ...sk.provenance },
      pendingReview: review?.skillPublish ? { id: review.id, version: review.skillPublish.toVersion, editClass: review.skillPublish.editClass, approvals: review.approvals.length, needed: review.skillPublish.approvalsNeeded } : undefined,
      publishCheck: publishCheck(sk),
    };
  };

  const visible = () => skills.filter((sk) => inTeam(sk.ownerTeam));
  const find = (sid: string) => {
    const sk = skills.find((x) => x.id === sid) ?? notFound('Skill');
    guardTeam(sk.ownerTeam, 'skill');
    return sk;
  };
  const audit = (sk: Stored | { ownerTeam: string; id?: string; name: string }, action: 'created' | 'edited' | 'published' | 'approved' | 'rejected' | 'restored' | 'deleted', summary: string, extra: { diff?: { field: string; before?: string; after?: string }[]; reason?: string } = {}) => {
    const name = 'versions' in sk ? newest(sk).content.name : sk.name;
    auditSink.log({ action, target: { type: 'skill', name, href: sk.id ? `/skills/${sk.id}` : undefined }, summary, owner: sk.ownerTeam, ...extra });
  };
  const auditAgent = (a: MockAgent, summary: string, diff: { field: string; before?: string; after?: string }[]) => auditSink.log({ action: 'edited', target: { type: 'agent', name: a.name, href: `/agents/${a.id}` }, summary, owner: a.owner, diff });

  /** Tools and knowledge bases the content needs that the agent does not hold. */
  function missingFor(a: Pick<Agent, 'toolIds' | 'collections'>, c: Pick<StoredContent, 'toolIds' | 'knowledgeBases'>) {
    return [...c.toolIds.filter((t) => !a.toolIds.includes(t)).map((t) => toolById(t)?.name ?? t), ...c.knowledgeBases.filter((k) => !a.collections.includes(k))];
  }

  /** An always-on skill is in every turn, so it needs no use-when line. */
  const validateContent = (c: { name?: string; useWhen?: string; loading?: SkillLoading; toolIds?: string[]; knowledgeBases?: string[] }) => {
    if (c.name !== undefined && !c.name.trim()) throw new ApiError('Name the skill.', 400);
    if (c.useWhen !== undefined) {
      if (!c.useWhen.trim() && c.loading !== 'always') throw new ApiError('Say when the skill should be used.', 400);
      if (c.useWhen.length > LIMITS.useWhenMaxChars) throw new ApiError(`“Use when” is ${c.useWhen.length} characters; the limit is ${LIMITS.useWhenMaxChars}.`, 400);
    }
    const unknownTool = c.toolIds?.find((t) => !toolById(t));
    if (unknownTool) throw new ApiError(`Unknown tool ${unknownTool}.`, 400);
    const kbs = deps.kbNames();
    const unknownKb = c.knowledgeBases?.find((k) => !kbs.includes(k));
    if (unknownKb) throw new ApiError(`Unknown knowledge base ${unknownKb}.`, 400);
  };

  const uniqueSlug = (name: string, team: string, except?: string) => {
    const base = slugify(name) || 'skill';
    let slug = base;
    for (let i = 2; skills.some((sk) => sk.id !== except && sk.ownerTeam === team && newest(sk).content.slug === slug); i++) slug = `${base}-${i}`.slice(0, 64);
    return slug;
  };

  function createStored(input: { name: string; useWhen: string; loading?: SkillLoading; instructions: string; ownerTeam: string; toolIds: string[]; knowledgeBases: string[]; guardrails: string[]; origin: SkillOrigin; provenance?: { detail: string; citations: SkillCitation[] }; tests?: SkillTestCaseInput[]; targetAgentIds?: string[]; resources?: SkillResource[]; note: string }) {
    validateContent(input);
    if (!deps.teams.includes(input.ownerTeam)) throw new ApiError('Choose the owner team.', 400);
    guardTeam(input.ownerTeam, 'skill');
    const sid = id('sk');
    const at = new Date().toISOString();
    const sk: Stored = {
      id: sid,
      ownerTeam: input.ownerTeam,
      origin: input.origin,
      provenance: input.provenance ?? { detail: input.origin === 'blank' ? `Written by ${me}` : '', citations: [] },
      versions: [
        {
          version: 1,
          state: 'draft',
          editClass: input.toolIds.length || input.knowledgeBases.length || input.guardrails.length ? 're_approval' : 're_test',
          note: input.note,
          changes: ['Created'],
          savedBy: me,
          savedAt: at,
          content: { name: input.name.trim(), slug: uniqueSlug(input.name, input.ownerTeam), useWhen: input.useWhen.trim(), loading: input.loading ?? 'on_match', instructions: input.instructions, toolIds: input.toolIds, knowledgeBases: input.knowledgeBases, guardrails: input.guardrails.filter((g) => g.trim()), resources: input.resources ?? [] },
        },
      ],
      tests: (input.tests ?? []).map((t) => ({ id: id('stc'), name: t.name.trim(), input: t.input.trim(), checks: t.checks, source: t.source ?? 'manual', sourceRef: t.sourceRef, createdAt: at, createdBy: me, lastOutcome: null })),
      runs: [],
      matchTerms: [],
      targetAgentIds: input.targetAgentIds ?? [],
    };
    skills.unshift(sk);
    return sk;
  }

  // ── Publish requests ──
  function openPublish(sk: Stored, by: string, note: string, createdAt = new Date().toISOString(), approvals: string[] = []): Review {
    const n = newest(sk);
    const pub = published(sk);
    const run = runFor(sk, n.version);
    const ec = editClassOf(sk, n.content);
    const needed = ec === 're_approval' ? 2 : 1;
    const name = n.content.name;
    const sp: SkillPublishRequest = {
      skillId: sk.id,
      skillName: name,
      ownerTeam: sk.ownerTeam,
      fromVersion: pub?.version ?? null,
      toVersion: n.version,
      editClass: ec,
      requestedBy: by,
      note,
      changes: n.changes,
      testRun: run ? { runId: run.id, version: run.version, ranAt: run.ranAt, passed: run.passed, total: run.total } : null,
      failing: run?.results.filter((r) => r.status === 'fail').map((r) => r.caseName) ?? [],
      toolsAdded: n.content.toolIds.filter((t) => !pub?.content.toolIds.includes(t)).map((t) => toolById(t)?.name ?? t),
      kbsAdded: n.content.knowledgeBases.filter((k) => !pub?.content.knowledgeBases.includes(k)),
      guardrails: n.content.guardrails,
      agents: [...new Set([...livePins(sk).map((p) => p.agentId), ...sk.targetAgentIds])].map((aid) => ({ name: agentOf(aid)?.name ?? aid, pinnedVersion: pins.find((p) => p.skillId === sk.id && p.agentId === aid)?.version ?? null })),
      approvalsNeeded: needed,
    };
    const review: Review = {
      id: `SKP-${++seq}`,
      title: `Publish ${name} v${n.version}`,
      customer: `Requested by ${by}`,
      workflowId: '',
      workflowName: name,
      agentSlug: '',
      kind: 'skill_publish',
      risk: ec === 're_approval' ? 'medium' : 'low',
      confidence: 1,
      proposal: note,
      actionTool: 'publish_skill',
      currency: 'CAD',
      policy: {
        id: 'gp_skill',
        name: ec === 're_approval' ? 'Skill publish · tools, knowledge or guardrails changed' : 'Skill publish',
        condition: ec === 're_approval' ? 'skill version changes tools, knowledge bases, guardrails or resources' : 'skill version changes wording',
        reviewers: `${sk.ownerTeam} publishers`,
        sla: '2 business days',
        onTimeout: 'Stays pending; the requester is notified',
        fourEyes: needed === 2,
      },
      slaMinutes: 16 * 60 - Math.round((Date.now() - new Date(createdAt).getTime()) / 60_000),
      assignee: approvals[0],
      approvals,
      status: approvals.length ? 'in_review' : 'pending',
      createdAt,
      reasoning: [run ? `${run.passed} of ${run.total} test cases pass on v${n.version}` : `No test run on v${n.version}`, ...n.changes],
      evidence: [],
      skillPublish: sp,
    };
    n.state = 'in_review';
    n.reviewId = review.id;
    deps.reviews().unshift(review);
    return review;
  }
  for (const seed of SKILL_SEEDS.filter((x) => x.review)) {
    const sk = skills.find((x) => x.id === seed.id)!;
    openPublish(sk, seed.review!.by, seed.review!.note, ago(seed.review!.minutesAgo / 1440), seed.review!.approvals ?? []);
  }

  function decide(r: Review, input: ReviewDecisionInput): Review {
    const sp = r.skillPublish!;
    if (!isOpen(r)) throw new ApiError(`${r.id} was already decided.`, 409);
    if (input.decision !== 'approved' && !input.reason?.trim()) throw new ApiError('A reason is required to reject or return.', 400);
    const sk = skills.find((x) => x.id === sp.skillId) ?? notFound('Skill');
    const v = sk.versions.find((x) => x.version === sp.toVersion) ?? notFound('Version');
    const now = new Date().toISOString();
    if (input.decision === 'approved') {
      if (sp.requestedBy === me) throw new ApiError('You requested this publish. Someone else on the team must approve it.', 409);
      if (r.approvals.includes(me)) throw new ApiError('You already approved this. A second approver must approve it.', 409);
      if (sp.failing.length && !input.reason?.trim()) throw new ApiError('Explain the failing tests before approving. The reason is kept with the version.', 400);
      r.approvals = [...r.approvals, me];
      if (r.approvals.length < sp.approvalsNeeded) {
        Object.assign(r, { status: 'in_review', assignee: me });
        audit(sk, 'approved', `Approved v${v.version} (1 of ${sp.approvalsNeeded})`, { reason: input.reason });
        return r;
      }
      for (const x of sk.versions) if (x.state === 'published') x.state = 'superseded';
      Object.assign(v, { state: 'published', publishedAt: now, publishedBy: me });
      Object.assign(r, { status: 'approved', decidedAt: now, decisionReason: input.reason, assignee: me });
      audit(sk, 'published', `Published v${v.version}`, { diff: [{ field: 'Published version', before: sp.fromVersion ? `v${sp.fromVersion}` : 'None', after: `v${v.version}` }], reason: input.reason });
      return r;
    }
    v.state = input.decision === 'rejected' ? 'rejected' : 'draft';
    v.reviewId = undefined;
    Object.assign(r, { status: input.decision, decidedAt: now, decisionReason: input.reason, assignee: r.assignee ?? me });
    audit(sk, 'rejected', `${input.decision === 'rejected' ? 'Rejected' : 'Returned'} v${v.version}`, { reason: input.reason });
    return r;
  }

  const wrapReviews = (inner: OpsApi['reviews']): OpsApi['reviews'] => ({
    ...inner,
    decide: async (rid, input) => {
      const r = deps.reviews().find((x) => x.id === rid);
      if (r?.kind === 'skill_publish') return respond(() => decide(r, input));
      return inner.decide(rid, input);
    },
    bulkDecide: async (ids, decision, reason, opts) => {
      const skillIds = ids.filter((rid) => deps.reviews().find((x) => x.id === rid)?.kind === 'skill_publish');
      const rest = ids.filter((rid) => !skillIds.includes(rid));
      const res: BulkResult = rest.length ? await inner.bulkDecide(rest, decision, reason, opts) : { updated: [], skipped: [] };
      return { updated: res.updated, skipped: [...res.skipped, ...skillIds.map((rid) => ({ id: rid, reason: 'Skill publishes need an individual decision' }))] };
    },
  });

  // ── Candidates for an agent that does not exist yet ──
  const pinnable = (sk: Stored) => sk.versions.filter((v) => v.state === 'published' || v.state === 'superseded');
  function candidatesFor(scope: SkillCandidateScope): SkillCandidates {
    const holder = { toolIds: scope.toolIds, collections: scope.knowledgeBases };
    const attachable: SkillCandidate[] = [];
    const blocked: SkillCandidates['blocked'] = [];
    for (const sk of skills) {
      const pub = published(sk);
      if (sk.deprecated || !pub) continue;
      if (sk.ownerTeam !== scope.ownerTeam && sk.ownerTeam !== 'Platform') {
        blocked.push({ skillId: sk.id, name: pub.content.name, kind: 'ownership', reason: `Belongs to ${sk.ownerTeam}` });
        continue;
      }
      const versions = pinnable(sk).map((v) => ({ version: v.version, current: v.version === pub.version, missing: missingFor(holder, v.content) }));
      if (versions.some((v) => !v.missing.length)) attachable.push({ skillId: sk.id, name: pub.content.name, useWhen: pub.content.useWhen, loading: pub.content.loading, ownerTeam: sk.ownerTeam, tokens: tokensOf(pub.content), versions });
      else blocked.push({ skillId: sk.id, name: pub.content.name, kind: 'access', reason: `Needs ${versions[0].missing.join(', ')}` });
    }
    return { attachable, blocked, limits: LIMITS };
  }
  /** Validates pins for a new agent before it is written, so a refused pin creates nothing. */
  function checkNewPins(scope: SkillCandidateScope, wanted: { skillId: string; version: number }[]) {
    if (wanted.length > LIMITS.maxAttached) throw new ApiError(`An agent can hold at most ${LIMITS.maxAttached} skills.`, 422);
    if (new Set(wanted.map((w) => w.skillId)).size !== wanted.length) throw new ApiError('Each skill can be pinned once.', 400);
    for (const w of wanted) {
      const sk = skills.find((x) => x.id === w.skillId) ?? notFound('Skill');
      const v = sk.versions.find((x) => x.version === w.version) ?? notFound('Version');
      const name = v.content.name;
      if (sk.deprecated) throw new ApiError(`${name} is deprecated and cannot be attached.`, 422);
      if (v.state !== 'published' && v.state !== 'superseded') throw new ApiError(`${name} v${w.version} is not published.`, 422);
      if (sk.ownerTeam !== scope.ownerTeam && sk.ownerTeam !== 'Platform') throw new ApiError(`${name} belongs to ${sk.ownerTeam}; only ${scope.ownerTeam} skills can be attached.`, 403);
      const missing = missingFor({ toolIds: scope.toolIds, collections: scope.knowledgeBases }, v.content);
      if (missing.length) throw new ApiError(`${name} v${w.version} needs ${missing.join(', ')}. Grant ${missing.length === 1 ? 'it' : 'them'} in Configure or remove the skill; a skill never grants access.`, 422);
    }
  }
  /** Pins on a new agent's version 1; no version bump, the create itself is the version. */
  function addNewPins(agentId: string, wanted: { skillId: string; version: number }[]) {
    const now = new Date().toISOString();
    for (const w of wanted) pins.push({ agentId, skillId: w.skillId, version: w.version, loads7d: 0, share7d: 0, attachedAt: now, attachedBy: me });
  }
  /** The published skills an agent pins, as template suggestions. */
  const pinnedOn = (agentId: string) =>
    pins
      .filter((p) => p.agentId === agentId)
      .map((p) => skills.find((x) => x.id === p.skillId))
      .filter((sk): sk is Stored => !!sk && !sk.deprecated && !!published(sk))
      .map((sk) => ({ skillId: sk.id, name: published(sk)!.content.name, reason: 'Attached to the source agent' }));
  const skillName = (sid: string) => {
    const sk = skills.find((x) => x.id === sid);
    return sk ? (published(sk) ?? newest(sk)).content.name : undefined;
  };

  // ── Agents ──
  const agentSkills = (a: MockAgent): AgentSkills => {
    const mine = pins.filter((p) => p.agentId === a.id);
    return {
      agentId: a.id,
      pins: mine
        .map((p): AgentSkillPin | null => {
          const sk = skills.find((x) => x.id === p.skillId);
          if (!sk) return null;
          const pv = sk.versions.find((v) => v.version === p.version) ?? newest(sk);
          const pub = published(sk);
          const upgradeAvailable = !!pub && !sk.deprecated && pub.version > p.version;
          const missing = pub ? missingFor(a, pub.content) : [];
          return { skillId: sk.id, name: pv.content.name, useWhen: pv.content.useWhen, loading: pv.content.loading, pinnedVersion: p.version, latestPublished: pub?.version ?? null, status: statusOf(sk), upgradeAvailable, upgradeBlocked: upgradeAvailable && missing.length ? `v${pub!.version} needs ${missing.join(', ')}` : undefined, loads7d: p.loads7d, share7d: p.share7d, tokens: tokensOf(pv.content) };
        })
        .filter((x): x is AgentSkillPin => !!x)
        .sort((x, y) => y.loads7d - x.loads7d),
      available: skills
        .filter((sk) => !sk.deprecated && published(sk) && !mine.some((p) => p.skillId === sk.id) && (sk.ownerTeam === a.owner || sk.ownerTeam === 'Platform'))
        .map((sk) => {
          const pub = published(sk)!;
          const missing = missingFor(a, pub.content);
          return { skillId: sk.id, name: pub.content.name, useWhen: pub.content.useWhen, loading: pub.content.loading, latestPublished: pub.version, ownerTeam: sk.ownerTeam, attachable: !missing.length, missing };
        }),
      limits: LIMITS,
    };
  };
  const agentOr404 = (aid: string) => {
    const a = agentOf(aid) ?? notFound('Agent');
    guardTeam(a.owner, 'agent');
    return a;
  };


  // ── Past work and generation ──
  async function pastWork(): Promise<PastWorkItem[]> {
    const page = { page: 1, pageSize: 100 };
    const [open, closed, chats] = await Promise.all([deps.cases.list({ ...page, view: 'team' }), deps.cases.list({ ...page, view: 'closed' }), deps.chat.threads.list({ ...page, pageSize: 30 })]);
    const cases = [...open.data, ...closed.data.filter((c) => !open.data.some((o) => o.id === c.id))];
    const lending = inTeam('Lending Ops') && mode() !== 'empty';
    return [
      ...cases.map((c): PastWorkItem => ({ id: c.id, kind: 'case', title: c.subject, detail: `${c.requester} · ${c.status === 'closed' ? 'resolved' : c.status.replace(/_/g, ' ')}`, group: `${c.intentName} · ${c.status === 'closed' ? 'resolved' : 'open'}`, at: c.receivedAt })),
      ...(lending ? ARCHIVED_CASES.map((c): PastWorkItem => ({ id: c.id, kind: c.kind, title: c.title, detail: c.detail, group: c.group, at: ago(c.daysAgo) })) : []),
      ...chats.data.map((t): PastWorkItem => ({ id: t.id, kind: 'chat', title: t.title, detail: `${t.agentName} · ${t.owner}`, group: `Chats with ${t.agentName}`, at: t.lastMessageAt })),
    ];
  }

  const draftContent = (d: SkillDraftForCheck): StoredContent => ({ name: d.name, slug: slugify(d.name), useWhen: d.useWhen, loading: d.loading ?? 'on_match', instructions: d.instructions, toolIds: d.toolIds, knowledgeBases: d.knowledgeBases, guardrails: d.guardrails, resources: [] });

  const exportText = (sk: Stored, v: StoredVersion) =>
    [
      `${v.content.slug}/SKILL.md`,
      '---',
      `name: ${v.content.slug}`,
      `description: ${v.content.useWhen}`,
      `allowed-tools: ${v.content.toolIds.map((t) => toolById(t)?.name ?? t).join(' ')}`,
      'metadata:',
      `  title: ${v.content.name}`,
      `  version: ${v.version}`,
      `  owner-team: ${sk.ownerTeam}`,
      `  knowledge-bases: ${v.content.knowledgeBases.join('; ')}`,
      ...v.content.guardrails.map((g) => `  guardrail: ${g}`),
      '---',
      '',
      v.content.instructions,
      ...v.content.resources.map((r) => `\n${v.content.slug}/${r.kind === 'template' ? 'assets' : 'references'}/${r.name}`),
    ].join('\n');

  function parseImport(fileId: string): SkillImportPreview {
    const f = deps.files.read(fileId);
    if (f.purpose !== 'skill_resource') throw new ApiError(`${f.name} was uploaded for something else; upload it here again.`, 400);
    const zip = f.name.toLowerCase().endsWith('.zip');
    const errors: string[] = [];
    const warnings: string[] = [];
    let fm: Record<string, string> = {};
    let body = '';
    if (zip) {
      const slug = slugify(f.name.replace(/\.zip$/i, '').replace(/-v\d+$/, ''));
      const title = slug.replace(/-/g, ' ');
      fm = { name: slug, description: `Use when a request is about ${title}.`, 'allowed-tools': topicOf(title) === 'dispute' ? 'get_transactions search_knowledge' : 'search_knowledge' };
      body = `## Steps\n1. Read the request.\n2. Follow the reference for ${title}.\n\n## Rules\n- Hand off when unsure.\n\n## Examples\n\n## Output format\nA short case note.`;
    } else if (f.text === undefined) {
      errors.push('The file could not be read. Upload a plain-text SKILL.md.');
    } else {
      const m = f.text.replace(/\r\n/g, '\n').match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
      if (!m) errors.push('No frontmatter. SKILL.md starts with a --- block holding name and description.');
      else {
        body = m[2].trim();
        let key = '';
        for (const line of m[1].split('\n')) {
          const kv = line.match(/^([\w-]+):\s*(.*)$/);
          if (kv) {
            key = kv[1];
            fm[key] = kv[2].replace(/^["']|["']$/g, '');
          } else if (key && /^\s*-\s+/.test(line)) fm[key] = `${fm[key] ?? ''} ${line.replace(/^\s*-\s+/, '')}`.trim();
        }
      }
    }
    const name = fm.name ?? '';
    const description = fm.description ?? '';
    if (!errors.length) {
      if (!name) errors.push('Frontmatter has no name.');
      else if (!SLUG.test(name) || name.length > 64) errors.push(`name “${name}” must be lowercase letters, numbers and hyphens, at most 64 characters.`);
      if (!description) errors.push('Frontmatter has no description.');
      else if (description.length > LIMITS.useWhenMaxChars) errors.push(`description is ${description.length} characters; the limit is ${LIMITS.useWhenMaxChars}.`);
      if (!body) warnings.push('The body is empty; write the instructions after importing.');
    }
    const tools = (fm['allowed-tools'] ?? '')
      .split(/[\s,]+/)
      .filter(Boolean)
      .map((requested) => {
        const t = deps.tools().find((x) => x.name === requested);
        return t ? { requested, toolId: t.id, name: t.name } : { requested };
      });
    for (const t of tools.filter((x) => !x.toolId)) warnings.push(`${t.requested} is not a tool in this bank; it is dropped.`);
    return {
      fileId,
      fileName: f.name,
      format: zip ? 'folder_zip' : 'skill_md',
      name: name ? name.replace(/-/g, ' ').replace(/^./, (c) => c.toUpperCase()) : '',
      slug: name,
      useWhen: description,
      instructions: body,
      resources: zip ? [{ name: 'references/procedure.md', size: Math.round(f.size * 0.4) }, { name: 'assets/reply-template.md', size: Math.round(f.size * 0.1) }] : [],
      tools,
      warnings,
      errors,
    };
  }

  const searchHits = (q: string): SearchHit[] =>
    mode() === 'empty'
      ? []
      : visible()
          .filter((sk) => `${newest(sk).content.name} ${newest(sk).content.slug} ${newest(sk).content.useWhen}`.toLowerCase().includes(q))
          .map((sk) => ({ id: sk.id, group: 'skills', title: newest(sk).content.name, detail: `${sk.ownerTeam} · ${statusOf(sk).replace('_', ' ')} · v${newest(sk).version}`, href: `/skills/${sk.id}` }));

  const VIEW: Record<Exclude<SkillView, 'all'>, (r: Skill) => boolean> = {
    published: (r) => r.status === 'published' || (r.status === 'in_review' && r.publishedVersion !== null),
    always: (r) => r.loading === 'always' && r.status !== 'deprecated',
    drafts: (r) => r.draftVersion !== null && r.status !== 'in_review' && r.status !== 'deprecated',
    in_review: (r) => r.status === 'in_review',
    deprecated: (r) => r.status === 'deprecated',
    unused: (r) => r.usedBy === 0 && r.status !== 'deprecated',
  };
  const facetValue = (r: Skill & { tools: string[]; knowledgeBases: string[] }, k: string) => (k === 'tools' ? r.tools : k === 'knowledgeBases' ? r.knowledgeBases : field(r, k));

  const api: SkillsApi = {
    list: (p) =>
      respond((m) => {
        const rows = visible().map((sk) => ({ ...row(sk), tools: newest(sk).content.toolIds.map((t) => toolById(t)?.name ?? t), knowledgeBases: newest(sk).content.knowledgeBases }));
        const src = m === 'empty' ? [] : rows;
        const inView = p.view === 'all' ? rows : rows.filter(VIEW[p.view]);
        const res = list(inView, p, { text: (r) => `${r.name} ${r.slug} ${r.useWhen} ${r.ownerTeam}`, value: facetValue, facetKeys: ['status', 'ownerTeam', 'tools', 'knowledgeBases', 'origin', 'loading'] }, m);
        return {
          ...res,
          data: res.data.map(({ tools: _t, knowledgeBases: _k, ...r }) => r),
          viewCounts: { all: src.length, published: src.filter(VIEW.published).length, always: src.filter(VIEW.always).length, drafts: src.filter(VIEW.drafts).length, in_review: src.filter(VIEW.in_review).length, deprecated: src.filter(VIEW.deprecated).length, unused: src.filter(VIEW.unused).length },
        };
      }),
    get: (sid) =>
      respond((m) => {
        if (m === 'empty') notFound('Skill');
        return detail(find(sid));
      }),
    create: (input) =>
      respond(() => {
        // Checked before anything is stored, so a refused review never leaves a half-saved skill behind.
        if (input.requestReview && !input.tests?.length) throw new ApiError('Add at least one test case before requesting review, or save as a draft.', 422);
        if (input.requestReview && !input.instructions.trim()) throw new ApiError('Write the instructions before requesting review.', 422);
        const sk = createStored({ ...input, note: input.origin === 'generated' ? 'Generated' : 'First draft', provenance: input.provenance ? { ...input.provenance, detail: input.gatewayCallId ? `${input.provenance.detail} · AI gateway call ${input.gatewayCallId}` : input.provenance.detail } : undefined });
        audit(sk, 'created', input.origin === 'generated' ? `Generated v1 with the AI gateway (${input.gatewayCallId ?? 'no call id'})` : 'Created v1', { diff: [{ field: 'Owner team', after: sk.ownerTeam }, { field: 'Tools', after: newest(sk).content.toolIds.map((t) => toolById(t)?.name).join(', ') || 'None' }] });
        if (sk.tests.length && input.requestReview) {
          const run = evaluate(sk, newest(sk).content, sk.tests);
          run.version = 1;
          sk.runs.unshift(run);
          markOutcomes(sk);
        }
        if (input.requestReview) {
          const r = openPublish(sk, me, input.reviewNote?.trim() || 'First version');
          audit(sk, 'edited', `Requested review of v1 (${r.id})`);
        }
        return row(sk);
      }),
    saveDraft: (sid, patch) =>
      respond(() => {
        const sk = find(sid);
        if (sk.deprecated) throw new ApiError('The skill is deprecated. Duplicate it to change it.', 409);
        const n = newest(sk);
        if (patch.baseVersion !== n.version) throw new ApiError(`v${n.version} was saved by ${n.savedBy} ${n.version > patch.baseVersion ? 'after you opened the page' : ''}. Reload to see it.`.replace(' .', '.'), 409);
        if (n.state === 'in_review') throw new ApiError(`v${n.version} is waiting in Reviews. Withdraw it there, or wait for the decision.`, 409);
        validateContent({ ...patch, loading: patch.loading ?? n.content.loading });
        const before = n.content;
        const nextContent: StoredContent = {
          ...structuredClone(before),
          name: patch.name?.trim() ?? before.name,
          useWhen: patch.useWhen?.trim() ?? before.useWhen,
          loading: patch.loading ?? before.loading,
          instructions: patch.instructions ?? before.instructions,
          toolIds: patch.toolIds ?? before.toolIds,
          knowledgeBases: patch.knowledgeBases ?? before.knowledgeBases,
          guardrails: patch.guardrails?.filter((g) => g.trim()) ?? before.guardrails,
        };
        const changes = [
          nextContent.name !== before.name && 'Name',
          nextContent.useWhen !== before.useWhen && 'Use when',
          nextContent.loading !== before.loading && 'Loading',
          nextContent.instructions !== before.instructions && 'Instructions',
          nextContent.toolIds.join() !== before.toolIds.join() && 'Tools',
          nextContent.knowledgeBases.join() !== before.knowledgeBases.join() && 'Knowledge bases',
          nextContent.guardrails.join() !== before.guardrails.join() && 'Guardrails',
        ].filter((x): x is string => !!x);
        if (!changes.length) throw new ApiError('Nothing changed.', 400);
        if (n.state === 'draft') {
          n.content = nextContent;
          n.changes = [...new Set([...n.changes.filter((c) => c !== 'Created'), ...changes.map((c) => `Changed ${c.toLowerCase()}`)])];
          n.note = patch.note?.trim() || n.note;
          n.savedAt = new Date().toISOString();
          n.savedBy = me;
          n.editClass = editClassOf(sk, nextContent);
        } else {
          sk.versions.unshift({ version: n.version + 1, state: 'draft', editClass: 're_test', note: patch.note?.trim() || `Changed ${changes.join(', ').toLowerCase()}`, changes: changes.map((c) => `Changed ${c.toLowerCase()}`), savedBy: me, savedAt: new Date().toISOString(), content: nextContent });
          newest(sk).editClass = editClassOf(sk, nextContent);
        }
        audit(sk, 'edited', `Saved draft v${newest(sk).version}`, { diff: changes.map((c) => ({ field: c, before: c === 'Tools' ? before.toolIds.map((t) => toolById(t)?.name).join(', ') : undefined, after: c === 'Tools' ? nextContent.toolIds.map((t) => toolById(t)?.name).join(', ') : 'changed' })) });
        markOutcomes(sk);
        return detail(sk);
      }),
    restore: (sid, v) =>
      respond(() => {
        const sk = find(sid);
        const src = sk.versions.find((x) => x.version === v) ?? notFound('Version');
        const n = newest(sk);
        if (n.state === 'in_review') throw new ApiError(`v${n.version} is waiting in Reviews. Decide it first.`, 409);
        if (n.state === 'draft') sk.versions.shift();
        const top = newest(sk);
        sk.versions.unshift({ version: top.version + 1, state: 'draft', editClass: 're_test', note: `Restored v${v}`, changes: [`Copied v${v} into a new draft`], savedBy: me, savedAt: new Date().toISOString(), content: structuredClone(src.content) });
        newest(sk).editClass = editClassOf(sk, newest(sk).content);
        audit(sk, 'restored', `Copied v${v} into draft v${newest(sk).version}`);
        markOutcomes(sk);
        return detail(sk);
      }),
    duplicate: (sid) =>
      respond(() => {
        const src = find(sid);
        const c = newest(src).content;
        const sk = createStored({ name: `${c.name} (copy)`, useWhen: c.useWhen, loading: c.loading, instructions: c.instructions, ownerTeam: src.ownerTeam, toolIds: c.toolIds, knowledgeBases: c.knowledgeBases, guardrails: c.guardrails, origin: 'duplicated', provenance: { detail: `Duplicated from ${c.name} v${newest(src).version}`, citations: [] }, tests: src.tests.map((t) => ({ name: t.name, input: t.input, checks: t.checks, source: t.source })), resources: structuredClone(c.resources), note: `Duplicated from ${c.name}` });
        sk.matchTerms = [...src.matchTerms];
        audit(sk, 'created', `Duplicated from ${c.name} v${newest(src).version}`);
        return row(sk);
      }),
    requestReview: (sid, note) =>
      respond(() => {
        const sk = find(sid);
        const check = publishCheck(sk);
        if (!check.canRequest) throw new ApiError(check.blockers.join(' '), 422);
        if (!note.trim()) throw new ApiError('Say what changed and why.', 400);
        const r = openPublish(sk, me, note.trim());
        audit(sk, 'edited', `Requested review of v${newest(sk).version} (${r.id})`, { reason: note });
        return detail(sk);
      }),
    deprecate: (sid, reason) =>
      respond(() => {
        const sk = find(sid);
        if (sk.deprecated) throw new ApiError('Already deprecated.', 409);
        if (!reason.trim()) throw new ApiError('Give a reason.', 400);
        if (openReview(sk)) throw new ApiError('A publish request is open. Decide it in Reviews first.', 409);
        sk.deprecated = { by: me, at: new Date().toISOString(), reason: reason.trim() };
        const pub = published(sk);
        if (pub) pub.state = 'deprecated';
        audit(sk, 'edited', 'Deprecated', { reason, diff: [{ field: 'Status', before: 'published', after: 'deprecated' }] });
        return detail(sk);
      }),
    remove: (sid) =>
      respond(() => {
        const sk = find(sid);
        const live = livePins(sk).filter((p) => agentOf(p.agentId)?.availability === 'published');
        if (live.length) throw new ApiError(`Pinned by ${live.map((p) => agentOf(p.agentId)!.name).join(', ')}, which ${live.length === 1 ? 'is' : 'are'} live. Detach it first.`, 409);
        if (openReview(sk)) throw new ApiError('A publish request is open. Decide it in Reviews first.', 409);
        for (let i = pins.length - 1; i >= 0; i--) if (pins[i].skillId === sid) pins.splice(i, 1);
        skills.splice(skills.indexOf(sk), 1);
        audit({ ownerTeam: sk.ownerTeam, name: newest(sk).content.name }, 'deleted', 'Deleted the skill');
      }),
    bulkDeprecate: (ids, reason) =>
      respond(() => {
        if (!reason.trim()) throw new ApiError('Give a reason.', 400);
        const out: BulkResult = { updated: [], skipped: [] };
        for (const sid of ids) {
          const sk = skills.find((x) => x.id === sid);
          if (!sk || !inTeam(sk.ownerTeam)) out.skipped.push({ id: sid, reason: 'Not found' });
          else if (sk.deprecated) out.skipped.push({ id: sid, reason: 'Already deprecated' });
          else if (!published(sk)) out.skipped.push({ id: sid, reason: 'Never published; delete it instead' });
          else if (openReview(sk)) out.skipped.push({ id: sid, reason: 'Publish request open' });
          else {
            sk.deprecated = { by: me, at: new Date().toISOString(), reason: reason.trim() };
            published(sk)!.state = 'deprecated';
            audit(sk, 'edited', 'Deprecated', { reason });
            out.updated.push(sid);
          }
        }
        return out;
      }),
    bulkRemove: (ids) =>
      respond(() => {
        const out: BulkResult = { updated: [], skipped: [] };
        for (const sid of ids) {
          const sk = skills.find((x) => x.id === sid);
          if (!sk || !inTeam(sk.ownerTeam)) {
            out.skipped.push({ id: sid, reason: 'Not found' });
            continue;
          }
          const live = livePins(sk).filter((p) => agentOf(p.agentId)?.availability === 'published');
          if (live.length) out.skipped.push({ id: sid, reason: `Pinned by ${plural(live.length, 'live agent')}` });
          else if (openReview(sk)) out.skipped.push({ id: sid, reason: 'Publish request open' });
          else {
            for (let i = pins.length - 1; i >= 0; i--) if (pins[i].skillId === sid) pins.splice(i, 1);
            skills.splice(skills.indexOf(sk), 1);
            audit({ ownerTeam: sk.ownerTeam, name: newest(sk).content.name }, 'deleted', 'Deleted the skill');
            out.updated.push(sid);
          }
        }
        return out;
      }),
    exportSkills: (ids, v) =>
      respond(() => {
        if (!ids.length) throw new ApiError('Choose at least one skill.', 400);
        const chosen = ids.map(find);
        const parts = chosen.map((sk) => {
          const ver = v ? (sk.versions.find((x) => x.version === v) ?? notFound('Version')) : (published(sk) ?? newest(sk));
          return { sk, ver, text: exportText(sk, ver) };
        });
        const one = parts.length === 1 ? parts[0] : null;
        const f = deps.files.writeExport({
          name: one ? `${one.ver.content.slug}-v${one.ver.version}.zip` : `skills-${ymd(new Date().toISOString())}.zip`,
          size: parts.reduce((n, p) => n + p.text.length, 0) + 2200 * parts.length,
          team: one ? one.sk.ownerTeam : (teamOwner() ?? chosen[0].ownerTeam),
          text: parts.map((p) => p.text).join('\n\n'),
          ref: one ? { type: 'skill', id: one.sk.id, name: `${one.ver.content.name} v${one.ver.version} export`, href: `/skills/${one.sk.id}` } : { type: 'skill', id: 'skills', name: `${plural(parts.length, 'skill')} export`, href: '/skills' },
        });
        for (const p of parts) audit(p.sk, 'edited', `Exported v${p.ver.version} as SKILL.md`);
        return f;
      }),

    tests: {
      add: (sid, input) =>
        respond(() => {
          const sk = find(sid);
          if (!input.name.trim() || !input.input.trim()) throw new ApiError('A test needs a name and an input.', 400);
          if (!input.checks.length) throw new ApiError('Add at least one check.', 400);
          const t: SkillTestCase = { id: id('stc'), name: input.name.trim(), input: input.input.trim(), checks: input.checks, source: input.source ?? 'manual', sourceRef: input.sourceRef, createdAt: new Date().toISOString(), createdBy: me, lastOutcome: null };
          sk.tests.push(t);
          return t;
        }),
      update: (sid, cid, input) =>
        respond(() => {
          const sk = find(sid);
          const t = sk.tests.find((x) => x.id === cid) ?? notFound('Test case');
          if (!input.name.trim() || !input.input.trim() || !input.checks.length) throw new ApiError('A test needs a name, an input and at least one check.', 400);
          Object.assign(t, { name: input.name.trim(), input: input.input.trim(), checks: input.checks, lastOutcome: null });
          return t;
        }),
      remove: (sid, cid) =>
        respond(() => {
          const sk = find(sid);
          const i = sk.tests.findIndex((x) => x.id === cid);
          if (i < 0) notFound('Test case');
          sk.tests.splice(i, 1);
        }),
      run: (sid) =>
        respond(() => {
          const sk = find(sid);
          if (!sk.tests.length) throw new ApiError('Add a test case first.', 422);
          const n = newest(sk);
          const run = evaluate(sk, n.content, sk.tests);
          run.version = n.version;
          sk.runs.unshift(run);
          markOutcomes(sk);
          return run;
        }),
    },

    resources: {
      add: (sid, input) =>
        respond(() => {
          const sk = find(sid);
          const n = newest(sk);
          if (n.state === 'in_review') throw new ApiError(`v${n.version} is waiting in Reviews.`, 409);
          const added: SkillResource[] = [];
          for (const fid of input.fileIds ?? []) {
            const f = deps.files.link(fid, { type: 'skill', id: sk.id, name: n.content.name, href: `/skills/${sk.id}?tab=resources` }, ['skill_resource', 'knowledge_source']);
            added.push({ id: id('res'), kind: 'file', name: f.name, fileId: f.id, size: f.size, addedAt: new Date().toISOString(), addedBy: me });
          }
          if (input.template) {
            if (!input.template.name.trim() || !input.template.body.trim()) throw new ApiError('A template needs a name and text.', 400);
            added.push({ id: id('res'), kind: 'template', name: input.template.name.trim(), body: input.template.body, addedAt: new Date().toISOString(), addedBy: me });
          }
          if (!added.length) throw new ApiError('Add a file or a template.', 400);
          const target = n.state === 'draft' ? n : null;
          if (target) target.content.resources.push(...added);
          else sk.versions.unshift({ version: n.version + 1, state: 'draft', editClass: 're_approval', note: 'Added resources', changes: added.map((r) => `Added ${r.name}`), savedBy: me, savedAt: new Date().toISOString(), content: { ...structuredClone(n.content), resources: [...n.content.resources, ...added] } });
          newest(sk).editClass = editClassOf(sk, newest(sk).content);
          audit(sk, 'edited', `Added ${added.map((r) => r.name).join(', ')} to v${newest(sk).version}`);
          return detail(sk);
        }),
      remove: (sid, rid) =>
        respond(() => {
          const sk = find(sid);
          const n = newest(sk);
          if (n.state === 'in_review') throw new ApiError(`v${n.version} is waiting in Reviews.`, 409);
          const r = n.content.resources.find((x) => x.id === rid) ?? notFound('Resource');
          if (n.state === 'draft') n.content.resources = n.content.resources.filter((x) => x.id !== rid);
          else sk.versions.unshift({ version: n.version + 1, state: 'draft', editClass: 're_approval', note: `Removed ${r.name}`, changes: [`Removed ${r.name}`], savedBy: me, savedAt: new Date().toISOString(), content: { ...structuredClone(n.content), resources: n.content.resources.filter((x) => x.id !== rid) } });
          newest(sk).editClass = editClassOf(sk, newest(sk).content);
          audit(sk, 'edited', `Removed ${r.name} from v${newest(sk).version}`);
          return detail(sk);
        }),
    },

    async *generate(input, signal) {
      const m = mode();
      const tick = (ms: number) => sleep(m === 'slow' ? ms * 3 : ms);
      await tick(350);
      if (m === 'error') {
        yield { type: 'error', message: 'The drafting model did not respond. Nothing was saved; try again.' };
        return;
      }
      if (!deps.teams.includes(input.scope.ownerTeam)) {
        yield { type: 'error', message: 'Choose the owner team in Scope.' };
        return;
      }
      const { pack, citations, status } = packFor(input.start, await pastWork());
      yield { type: 'status', text: status };
      await tick(500);
      if (signal?.aborted) return;
      yield { type: 'field', field: 'name', value: pack.name };
      await tick(150);
      yield { type: 'field', field: 'useWhen', value: pack.useWhen };
      for (const k of ['steps', 'rules', 'examples', 'output_format'] as SkillSectionKey[]) {
        const parts = pack.sections[k].match(/\S+\s*/g) ?? [];
        for (let i = 0; i < parts.length; i += 3) {
          if (signal?.aborted) return;
          await tick(22);
          yield { type: 'section', section: k, delta: parts.slice(i, i + 3).join('') };
        }
      }
      const toolIds = pack.tools.map(toolIdOf).filter((x): x is string => !!x);
      const kbs = pack.knowledgeBases.filter((k) => deps.kbNames().includes(k));
      const warnings: SkillWarning[] = [
        ...toolIds.filter((t) => !input.scope.toolIds.includes(t)).map((t): SkillWarning => ({ kind: 'tool_out_of_scope', ref: t, message: `The draft calls ${toolById(t)?.name}, which is not in scope.` })),
        ...kbs.filter((k) => !input.scope.knowledgeBases.includes(k)).map((k): SkillWarning => ({ kind: 'kb_out_of_scope', ref: k, message: `The draft cites ${k}, which is not in scope.` })),
        ...input.scope.targetAgentIds.flatMap((aid) => {
          const a = agentOf(aid);
          return a ? missingFor(a, { toolIds: toolIds.filter((t) => input.scope.toolIds.includes(t)), knowledgeBases: kbs.filter((k) => input.scope.knowledgeBases.includes(k)) }).map((x): SkillWarning => ({ kind: 'agent_lacks', ref: `${aid}:${x}`, message: `${a.name} does not hold ${x}; it cannot use this skill until it is granted.` })) : [];
        }),
      ];
      const gatewayCallId = `gw_${Math.random().toString(36).slice(2, 10)}`;
      const skill: GeneratedSkill = { name: pack.name, slug: slugify(pack.name), useWhen: pack.useWhen, sections: pack.sections, tools: refs(toolIds), knowledgeBases: kbs, guardrails: pack.guardrails, citations: citations.map((c, i) => ({ ...c, id: `gcit_${i}` })), warnings, model: 'ops-drafting', gatewayCallId };
      auditSink.log({ action: 'created', target: { type: 'skill', name: pack.name }, summary: `Drafted a skill with the AI gateway (${gatewayCallId}); not saved yet`, owner: input.scope.ownerTeam });
      yield { type: 'done', skill };
    },
    rewriteSection: (input) =>
      respond(() => {
        if (!input.instruction.trim()) throw new ApiError('Say how to rewrite it.', 400);
        return { text: rewrite(input.section, input.current, input.instruction), gatewayCallId: `gw_${Math.random().toString(36).slice(2, 10)}` };
      }),
    suggestTests: async (input, skill) => {
      const items = input.start.kind === 'past_work' ? (await pastWork()).filter((p) => (input.start as { itemIds: string[] }).itemIds.includes(p.id)) : [];
      return respond(() => {
        const { pack } = packFor(input.start, items);
        const toolNames = skill.tools.map((t) => t.name);
        const fromPack = pack.tests.map((t) => ({ name: t.name, input: t.input, checks: t.checks.filter((c) => !(c.type === 'calls_tool' && !toolNames.includes(c.tool ?? ''))), source: 'generated' as const }));
        const fromCases = items.filter((i) => i.kind === 'case').slice(0, 3).map((i) => ({ name: i.title.slice(0, 48), input: i.title, checks: [...(toolNames[0] ? [{ type: 'calls_tool' as const, tool: toolNames[0] }] : []), ...(skill.knowledgeBases[0] ? [{ type: 'cites' as const, source: skill.knowledgeBases[0] }] : []), { type: 'reply_not_contains' as const, text: 'approved' }], source: 'case' as const, sourceRef: i.id }));
        return [...fromCases, ...fromPack].filter((t) => t.checks.length).slice(0, 6);
      });
    },
    dryRun: (draft, tests) =>
      respond(() => {
        if (!tests.length) throw new ApiError('Add a test case first.', 400);
        const c = draftContent(draft);
        const run = evaluate(null, c, tests.map((t, i) => ({ ...t, id: `dry_${i}` })));
        run.version = 0;
        return run;
      }),
    impact: (draft, agentIds) =>
      respond(() =>
        agentIds.map((aid): SkillImpact => {
          const a = agentOf(aid) ?? notFound('Agent');
          const current = pins.filter((p) => p.agentId === aid).map((p) => newest(skills.find((sk) => sk.id === p.skillId)!)?.content.name ?? p.skillId);
          const toolsNeeded = draft.toolIds.map((t) => toolById(t)?.name ?? t);
          const toolsHeld = draft.toolIds.filter((t) => a.toolIds.includes(t)).map((t) => toolById(t)?.name ?? t);
          const kbsHeld = draft.knowledgeBases.filter((k) => a.collections.includes(k));
          const toolsMissing = toolsNeeded.filter((t) => !toolsHeld.includes(t));
          const kbsMissing = draft.knowledgeBases.filter((k) => !kbsHeld.includes(k));
          return { agentId: a.id, agentName: a.name, skillsBefore: current, skillsAfter: [...current, draft.name], toolsHeld, toolsMissing, kbsHeld, kbsMissing, guardrailsAdded: draft.guardrails, tokens: tokensOf({ instructions: draft.instructions, guardrails: draft.guardrails }), attachable: !toolsMissing.length && !kbsMissing.length && current.length < LIMITS.maxAttached };
        }),
      ),
    generateOptions: async () => {
      const past = await pastWork();
      return respond(() => ({
        templates: TEMPLATES,
        documents: DOCUMENTS.filter((d) => deps.kbNames().includes(d.kb)).map(({ id: did, title, kb, detail: d }) => ({ id: did, title, kb, detail: d })),
        pastWork: past,
        tools: refs(deps.tools().filter((t) => t.enabled).map((t) => t.id)),
        knowledgeBases: deps.kbNames(),
        agents: deps.agents().filter((a) => inTeam(a.owner)).map((a) => ({ id: a.id, name: a.name, owner: a.owner, toolIds: a.toolIds, collections: a.collections })),
        teams: deps.teams.filter((t) => inTeam(t)),
        limits: LIMITS,
      }));
    },
    options: () => respond(() => ({ teams: deps.teams.filter((t) => inTeam(t)), tools: refs(deps.tools().filter((t) => t.enabled).map((t) => t.id)), knowledgeBases: deps.kbNames(), limits: LIMITS })),
    candidates: (scope) => respond((m) => (m === 'empty' ? { attachable: [], blocked: [], limits: LIMITS } : candidatesFor(scope))),
    previewImport: (fileId) => respond(() => parseImport(fileId)),
    importSkill: (fileId, ownerTeam) =>
      respond(() => {
        const p = parseImport(fileId);
        if (p.errors.length) throw new ApiError(p.errors.join(' '), 422);
        const sk = createStored({
          name: p.name,
          useWhen: p.useWhen,
          instructions: p.instructions,
          ownerTeam,
          toolIds: p.tools.map((t) => t.toolId).filter((x): x is string => !!x),
          knowledgeBases: [],
          guardrails: [],
          origin: 'imported',
          provenance: { detail: `Imported from ${p.fileName}`, citations: [] },
          resources: p.resources.map((r) => ({ id: id('res'), kind: 'file', name: r.name, fileId, size: r.size, addedAt: new Date().toISOString(), addedBy: me })),
          note: `Imported from ${p.fileName}`,
        });
        newest(sk).content.slug = uniqueSlug(p.slug, ownerTeam, sk.id);
        deps.files.link(fileId, { type: 'skill', id: sk.id, name: p.name, href: `/skills/${sk.id}` }, ['skill_resource']);
        audit(sk, 'created', `Imported from ${p.fileName}`, { diff: p.tools.filter((t) => !t.toolId).map((t) => ({ field: 'Dropped tool', before: t.requested })) });
        return row(sk);
      }),

    agents: {
      get: (aid) =>
        respond((m) => {
          const a = agentOr404(aid);
          return m === 'empty' ? { agentId: aid, pins: [], available: [], limits: LIMITS } : agentSkills(a);
        }),
      options: (aid, p, loading) =>
        respond(() =>
          pageOptions(
            agentSkills(agentOr404(aid))
              .available.filter((x) => !loading || x.loading === loading)
              .map((x) => ({ id: x.skillId, label: x.name, hint: `v${x.latestPublished} · ${x.useWhen}`, disabled: x.attachable ? null : `Needs ${x.missing.join(', ')}; grant them on this agent first.` })),
            p,
          ),
        ),
      attach: (aid, sid, wanted) =>
        respond(() => {
          const a = agentOr404(aid);
          const sk = skills.find((x) => x.id === sid) ?? notFound('Skill');
          // No version attaches the latest published one, as the picker offers it.
          const v = wanted ?? published(sk)?.version ?? notFound('Published version');
          const target = sk.versions.find((x) => x.version === v) ?? notFound('Version');
          const existing = pins.find((p) => p.agentId === aid && p.skillId === sid);
          if (sk.deprecated) throw new ApiError(`${target.content.name} is deprecated and cannot be attached or moved.`, 422);
          if (target.state !== 'published' && target.state !== 'superseded') throw new ApiError(`v${v} is not published.`, 422);
          if (sk.ownerTeam !== a.owner && sk.ownerTeam !== 'Platform') throw new ApiError(`${target.content.name} belongs to ${sk.ownerTeam}; only ${a.owner} skills can be attached to ${a.name}.`, 403);
          const missing = missingFor(a, target.content);
          if (missing.length) throw new ApiError(`${a.name} does not hold ${missing.join(', ')}. Grant ${missing.length === 1 ? 'it' : 'them'} on the agent first; a skill never grants access.`, 422);
          if (!existing && pins.filter((p) => p.agentId === aid).length >= LIMITS.maxAttached) throw new ApiError(`${a.name} already has ${LIMITS.maxAttached} skills, the most an agent can hold.`, 422);
          if (existing?.version === v) throw new ApiError(`Already pinned to v${v}.`, 409);
          const note = existing ? `Moved ${target.content.name} from v${existing.version} to v${v}` : `Attached ${target.content.name} v${v}`;
          if (existing) existing.version = v;
          else pins.push({ agentId: aid, skillId: sid, version: v, loads7d: 0, share7d: 0, attachedAt: new Date().toISOString(), attachedBy: me });
          deps.bumpAgent(aid, note);
          auditAgent(a, note, [{ field: 'Skill', before: existing ? `${target.content.name} v${existing.version}` : undefined, after: `${target.content.name} v${v}` }]);
          return agentSkills(agentOf(aid)!);
        }),
      detach: (aid, sid) =>
        respond(() => {
          const a = agentOr404(aid);
          const i = pins.findIndex((p) => p.agentId === aid && p.skillId === sid);
          if (i < 0) notFound('Attached skill');
          const p = pins[i];
          const name = skills.find((x) => x.id === sid)?.versions.find((x) => x.version === p.version)?.content.name ?? sid;
          pins.splice(i, 1);
          const note = `Detached ${name} v${p.version}`;
          deps.bumpAgent(aid, note);
          auditAgent(a, note, [{ field: 'Skill', before: `${name} v${p.version}` }]);
          return agentSkills(agentOf(aid)!);
        }),
    },
  };

  /** Team-scoped rows for the ⌘K palette. */
  const search = (q: string) => searchHits(q.trim().toLowerCase());
  /** Owner team of a skill publish review, for review team scoping. */
  const reviewOwner = (r: Review) => r.skillPublish?.ownerTeam;

  /** Each skill as a suite for Assurance: its test cases and the runs on its newest and published versions. */
  const suiteView = () =>
    skills
      .filter((sk) => !sk.deprecated)
      .map((sk) => {
        const n = newest(sk);
        const pub = published(sk);
        return { id: sk.id, name: n.content.name, ownerTeam: sk.ownerTeam, version: n.version, publishedVersion: pub?.version ?? null, tests: sk.tests.map((t) => ({ id: t.id, name: t.name, input: t.input })), pinnedAgentIds: pins.filter((p) => p.skillId === sk.id).map((p) => p.agentId), runs: sk.runs.map((r) => ({ ...r, reviewId: sk.versions.find((v) => v.version === r.version)?.reviewId })), candidate: runFor(sk, n.version) ?? null, live: pub ? (runFor(sk, pub.version) ?? null) : null };
      });

  return { api, wrapReviews, search, reviewOwner, newAgentPins: { check: checkNewPins, add: addNewPins }, pinnedOn, skillName, suiteView };
}
