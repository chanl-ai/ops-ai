import type { Agent, AgentPublishRequest, AgentVersion, AgentVersionState, Review, Risk, Version, WorkflowGraph } from '@/lib/types/domain';

import { ApiError, type OpsApi } from '../../contract';
import type { EvalsMock } from '../evals';
import { bulk, notFound, respond } from '../runtime';
import { AGENT_PUBLISH_SEED, seedPublished } from './seed';

const isOpen = (r: Review) => r.status === 'pending' || r.status === 'in_review';
const ORDER: Risk[] = ['low', 'medium', 'high', 'critical'];
/** Injection pass rate each tier requires (spec 04, 5.4). */
const INJECTION_THRESHOLD: Record<Risk, number> = { low: 0.95, medium: 0.98, high: 1, critical: 1 };

interface VersionMeta {
  publishedAt?: string;
  publishedBy?: string;
  reviewId?: string;
  rejectedReason?: string;
  returnedReason?: string;
}

/**
 * Which agent version is published, and what happened to each version. Created before the agent rows and
 * graph pins are built so both can read it; the publish flow below writes to it.
 */
export function createAgentVersionStore(agents: { id: string; version: number }[]) {
  const published: Record<string, number | null> = {};
  const meta: Record<string, Record<number, VersionMeta>> = {};
  for (const a of agents) published[a.id] = seedPublished(a);
  return {
    /** Agents created after the seed start unpublished. */
    publishedOf: (aid: string) => published[aid] ?? null,
    publish: (aid: string, version: number, m: VersionMeta) => {
      published[aid] = version;
      ((meta[aid] ??= {})[version] = { ...meta[aid]?.[version], ...m });
    },
    meta: (aid: string, version: number): VersionMeta => ((meta[aid] ??= {})[version] ??= {}),
  };
}
export type AgentVersionStore = ReturnType<typeof createAgentVersionStore>;

export interface AgentPublishDeps {
  store: AgentVersionStore;
  agents: () => Agent[];
  /** Versions as saved, newest first; the store adds state. */
  versions: (aid: string) => Version[];
  reviews: () => Review[];
  evals: EvalsMock;
  workflowTier: (workflowId: string) => Risk;
  /** Highest access class among the agent's granted tools. */
  toolAccess: (agentId: string) => 'read' | 'write' | undefined;
  me: string;
  /** Runs after a version is published, so the agent's wrapper workflow can follow it. */
  onPublished?: (agentId: string, version: number) => void;
}

/**
 * Agent publishing (spec 01 4.5, spec 04 5.11). Saves create draft versions; an `agent_publish` review in the
 * shared queue publishes one, decided by someone other than the requester and the author; workflows pin
 * published versions only.
 */
export function createAgentPublishMock(deps: AgentPublishDeps) {
  const { store } = deps;
  const agentOr404 = (aid: string) => deps.agents().find((a) => a.id === aid) ?? notFound('Agent');
  const openReviewOf = (aid: string) => deps.reviews().find((r) => r.kind === 'agent_publish' && isOpen(r) && r.agentPublish?.agentId === aid);

  const stateOf = (a: Agent, v: number): AgentVersionState => {
    const m = store.meta(a.id, v);
    if (m.rejectedReason) return 'rejected';
    const open = openReviewOf(a.id);
    if (open?.agentPublish?.version === v) return 'in_review';
    const pub = store.publishedOf(a.id);
    if (v === pub) return 'published';
    if (m.publishedAt || (pub !== null && v < pub)) return 'superseded';
    // An older draft replaced by a newer save is never published.
    return v < a.version ? 'superseded' : 'draft';
  };

  const versionsView = (aid: string): AgentVersion[] => {
    const a = agentOr404(aid);
    const pub = store.publishedOf(aid);
    return deps.versions(aid).map((v) => {
      const m = store.meta(aid, v.version);
      const state = stateOf(a, v.version);
      // Seeded history has no publish records: a published or superseded seed version was published when saved.
      const seededPublish = !m.publishedAt && (state === 'published' || (state === 'superseded' && pub !== null && v.version < pub));
      const { publishedAt, publishedBy, ...rest } = v;
      return {
        ...rest,
        current: v.version === pub,
        state,
        savedAt: publishedAt,
        savedBy: publishedBy,
        publishedAt: m.publishedAt ?? (seededPublish ? publishedAt : undefined),
        publishedBy: m.publishedBy ?? (seededPublish ? publishedBy : undefined),
        reviewId: m.reviewId ?? (state === 'in_review' ? openReviewOf(aid)?.id : undefined),
        decisionReason: m.rejectedReason ?? m.returnedReason,
      };
    });
  };

  const tierFor = (a: Agent): { tier: Risk; reason: string } => {
    const live = a.usedIn.filter((u) => u.status === 'live');
    if (live.length) {
      const tiers = live.map((u) => ({ name: u.workflowName, tier: deps.workflowTier(u.workflowId) }));
      const top = tiers.reduce((x, y) => (ORDER.indexOf(y.tier) > ORDER.indexOf(x.tier) ? y : x));
      return { tier: top.tier, reason: `Highest tier among the live workflows that pin it: ${top.name} (${top.tier})` };
    }
    const access = deps.toolAccess(a.id);
    const tier: Risk = access === 'write' ? 'medium' : 'low';
    return { tier, reason: access ? `No live workflow pins it; its ${access} tools set the tier` : 'No live workflow pins it and it holds no write tools' };
  };

  const bodyFor = (a: Agent, version: number, note: string, requestedBy: string): AgentPublishRequest => {
    const { tier, reason } = tierFor(a);
    const pub = store.publishedOf(a.id);
    const candidate = deps.evals.summaryFor(a.id, version);
    const published = pub !== null ? deps.evals.summaryFor(a.id, pub) : null;
    const blockers: string[] = [];
    let failing = 0;
    if (deps.evals.isRunning(a.id, version)) blockers.push(`Evals for v${version} are still running.`);
    else if (!candidate) blockers.push(`v${version} has no eval run.`);
    else {
      const inj = candidate.injection;
      if (inj.regressions) blockers.push(`${inj.regressions === 1 ? '1 injection case regressed' : `${inj.regressions} injection cases regressed`} against the published version.`);
      else if (inj.total && inj.passed / inj.total < INJECTION_THRESHOLD[tier]) blockers.push(`${inj.passed} of ${inj.total} injection cases pass; tier ${tier} needs ${Math.round(INJECTION_THRESHOLD[tier] * 100)}%.`);
      failing = candidate.total - candidate.passed - (inj.total - inj.passed);
      // Spec 04 5.10.6 AG5: failing cases are advisory at low and block at medium and above.
      if (failing > 0 && tier !== 'low') blockers.push(`${failing === 1 ? '1 eval case fails' : `${failing} eval cases fail`}; tier ${tier} needs every case to pass.`);
    }
    const saved = deps.versions(a.id).find((v) => v.version === version);
    return { agentId: a.id, agentName: a.name, version, fromVersion: pub, note, requestedBy, savedBy: saved?.publishedBy ?? requestedBy, tier, tierReason: reason, approvalsNeeded: tier === 'high' || tier === 'critical' ? 2 : 1, candidate, published, failing, blockers };
  };

  const POLICY = (a: Agent, fourEyes: boolean): Review['policy'] => ({ id: 'gp_agent_publish', name: 'Agent publish', condition: 'every agent version before a workflow can pin it', reviewers: `${a.owner} publishers`, sla: '1 business day', onTimeout: 'Stays pending; the requester is notified', fourEyes });
  const createReview = (a: Agent, version: number, note: string, by: string, createdAt = new Date().toISOString()): Review => {
    const body = bodyFor(a, version, note, by);
    const n = deps.reviews().filter((r) => r.kind === 'agent_publish').length;
    const saved = deps.versions(a.id).find((v) => v.version === version);
    const r: Review = {
      id: `AGP-${1001 + n}`,
      title: `Publish ${a.name} v${version}`,
      customer: `Requested by ${by}`,
      workflowId: '',
      workflowName: a.name,
      agentSlug: a.slug,
      kind: 'agent_publish',
      risk: body.tier,
      confidence: body.candidate ? body.candidate.passed / Math.max(1, body.candidate.total) : 1,
      proposal: note,
      actionTool: 'publish_agent',
      currency: 'CAD',
      policy: POLICY(a, body.approvalsNeeded === 2),
      slaMinutes: 8 * 60 - Math.round((Date.now() - new Date(createdAt).getTime()) / 60_000),
      approvals: [],
      status: 'pending',
      createdAt,
      reasoning: [body.candidate ? `${body.candidate.passed} of ${body.candidate.total} eval cases pass on v${version}` : `No eval run on v${version}`, ...(saved?.changes ?? [])],
      evidence: [],
      agentPublish: body,
    };
    deps.reviews().unshift(r);
    store.meta(a.id, version).returnedReason = undefined;
    return r;
  };

  // Seed the open review once the review list exists.
  const seedReviews = () => {
    for (const [aid, s] of Object.entries(AGENT_PUBLISH_SEED)) {
      const a = deps.agents().find((x) => x.id === aid);
      if (!a || !s.openReview) continue;
      // The requester saved the seeded draft, so maker-checker leaves the demo user free to decide it.
      const saved = deps.versions(aid).find((v) => v.version === a.version);
      if (saved) saved.publishedBy = s.openReview.by;
      createReview(a, a.version, s.openReview.note, s.openReview.by, new Date(Date.now() - s.openReview.minutesAgo * 60_000).toISOString());
    }
  };

  /** Decided reviews keep the body they were decided on; open ones refresh, so a finished eval run unblocks them. */
  const enrich = (r: Review): Review => {
    if (r.kind !== 'agent_publish' || !r.agentPublish || !isOpen(r)) return r;
    const a = deps.agents().find((x) => x.id === r.agentPublish!.agentId);
    if (!a) return r;
    const body = bodyFor(a, r.agentPublish.version, r.agentPublish.note, r.agentPublish.requestedBy);
    return { ...r, risk: body.tier, policy: POLICY(a, body.approvalsNeeded === 2), agentPublish: { ...body, fromVersion: r.agentPublish.fromVersion } };
  };

  const decide = (r: Review, input: Parameters<OpsApi['reviews']['decide']>[1]): Review => {
    if (!isOpen(r)) throw new ApiError(`${r.id} was already decided.`, 409);
    const a = agentOr404(r.agentPublish!.agentId);
    const body = enrich(r).agentPublish!;
    const v = body.version;
    if (input.decision !== 'approved') {
      if (!input.reason?.trim()) throw new ApiError('A reason is required to reject or return.', 400);
      if (input.decision === 'rejected') store.meta(a.id, v).rejectedReason = input.reason;
      else store.meta(a.id, v).returnedReason = input.reason;
      store.meta(a.id, v).reviewId = r.id;
      Object.assign(r, { status: input.decision, decidedAt: new Date().toISOString(), decisionReason: input.reason, assignee: r.assignee ?? deps.me, agentPublish: body });
      return r;
    }
    if (body.requestedBy === deps.me) throw new ApiError('You requested this publish. Another publisher must approve it.', 409);
    if (body.savedBy === deps.me) throw new ApiError(`You saved v${v}. Another publisher must approve it.`, 409);
    if (r.approvals.includes(deps.me)) throw new ApiError('You already approved this. A second publisher from the second line must approve it.', 409);
    if (body.blockers.length) throw new ApiError(`Publishing is blocked. ${body.blockers.join(' ')}`, 422);
    if (body.failing > 0 && !input.reason?.trim()) throw new ApiError('Explain the failing eval cases before approving. The reason is kept with the version.', 400);
    if (body.approvalsNeeded === 2 && !r.approvals.length) {
      Object.assign(r, { approvals: [deps.me], assignee: deps.me, status: 'in_review', agentPublish: body });
      return r;
    }
    const at = new Date().toISOString();
    store.publish(a.id, v, { publishedAt: at, publishedBy: deps.me, reviewId: r.id });
    Object.assign(r, { status: 'approved', decidedAt: at, decisionReason: input.reason, assignee: deps.me, approvals: [...r.approvals, deps.me], agentPublish: body });
    deps.onPublished?.(a.id, v);
    return r;
  };

  const wrapReviews = (inner: OpsApi['reviews']): OpsApi['reviews'] => ({
    ...inner,
    list: async (p) => {
      const res = await inner.list(p);
      return { ...res, data: res.data.map(enrich) };
    },
    get: async (rid) => enrich(await inner.get(rid)),
    decide: async (rid, input) => {
      const r = deps.reviews().find((x) => x.id === rid);
      if (r?.kind === 'agent_publish') {
        await respond(() => decide(r, input));
        return inner.get(rid);
      }
      return inner.decide(rid, input);
    },
    bulkDecide: async (ids, decision, reason, opts) => {
      const mine = ids.filter((rid) => deps.reviews().find((x) => x.id === rid)?.kind === 'agent_publish');
      const rest = ids.filter((rid) => !mine.includes(rid));
      const res = rest.length ? await inner.bulkDecide(rest, decision, reason, opts) : { updated: [], skipped: [] };
      return { updated: res.updated, skipped: [...res.skipped, ...bulk(mine, () => 'Agent publishes need an individual decision').skipped] };
    },
  });

  const requestPublish = (aid: string, version: number, note: string): Review => {
    const a = agentOr404(aid);
    if (openReviewOf(aid)) throw new ApiError(`${a.name} already has a publish request waiting (${openReviewOf(aid)!.id}). Decide or return it first.`, 409);
    if (version !== a.version) throw new ApiError(`Only the newest version, v${a.version}, can be sent for publish.`, 422);
    if (store.publishedOf(aid) === version) throw new ApiError(`v${version} is already published.`, 422);
    if (store.meta(aid, version).rejectedReason) throw new ApiError(`v${version} was rejected. Save a new version to try again.`, 422);
    if (!note.trim()) throw new ApiError('Add a note saying what changed.', 400);
    return createReview(a, version, note.trim(), deps.me);
  };

  /**
   * Agent versions a workflow publish would pin that are not published (spec 01 5.5.12). A workflow publish pins
   * each agent's newest version, so a draft ahead of the published one has to be published first.
   */
  const unpublishedPins = (graph: WorkflowGraph): string[] => {
    const slugs = [...new Set(graph.nodes.map((n) => n.data.agentSlug as string | undefined).filter((s): s is string => !!s))];
    return slugs.flatMap((slug) => {
      const a = deps.agents().find((x) => x.slug === slug);
      if (!a || store.publishedOf(a.id) === a.version) return [];
      const state = stateOf(a, a.version);
      return [`${a.name} v${a.version} (${state === 'in_review' ? `in review, ${openReviewOf(a.id)?.id}` : state})`];
    });
  };

  return { requestPublish, versionsView, wrapReviews, unpublishedPins, seedReviews, withBody: enrich };
}
