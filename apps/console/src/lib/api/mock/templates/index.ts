import type { Agent, AgentGuardrails, BulkResult, Channel, Review, ReviewDecisionInput, Tool, Version } from '@/lib/types/domain';
import type { EvalCaseInput } from '@/lib/types/evals';
import type { SkillCandidateScope } from '@/lib/types/skills';
import type { AgentTemplate, AgentTemplateDetail, CreateFromTemplateInput, SkillPinInput, TemplateDiffRow, TemplateSkillSuggestion, TemplateSubmissionRequest } from '@/lib/types/templates';

import { ApiError, type OpsApi } from '../../contract';
import type { TemplatesApi } from '../../templates-contract';
import { auditSink } from '../governance';
import { field, id, list, notFound, respond } from '../runtime';
import { inTeam, teamDirectory, teamOwner } from '../teams';
import { TEMPLATE_SEEDS, TEMPLATE_SKILLS } from './seed';

export interface TemplatesDeps {
  me: string;
  kbNames: () => string[];
  /** Tools the current team may grant. */
  teamTools: () => Tool[];
  /** Creates the agent at version 1 with every field set; throws 409 on a taken handle. */
  insertAgent: (fields: { name: string; role: string; model: string; owner: string; channels: Channel[]; instructions: string; toolIds: string[]; collections: string[]; guardrails: AgentGuardrails }, note: string) => { id: string; name: string };
  agentContent: (agentId: string) => { name: string; role: string; model: string; owner: string; channels: Channel[]; instructions: string; toolNames: string[]; toolAccess: Record<string, Tool['access']>; collections: string[]; guardrails: AgentGuardrails; version: number };
  addCase: (agentId: string, input: EvalCaseInput) => Promise<unknown>;
  /** The shared review queue; submissions are `template_submission` reviews in it. */
  reviews: () => Review[];
  skills: {
    /** Throws when a pin is not allowed for an agent with this scope. */
    check: (scope: SkillCandidateScope, pins: SkillPinInput[]) => void;
    add: (agentId: string, pins: SkillPinInput[]) => void;
    pinnedOn: (agentId: string) => TemplateSkillSuggestion[];
    name: (skillId: string) => string | undefined;
  };
}

type AgentRecord = Omit<Agent, 'usedIn' | 'publishedVersion' | 'availability' | 'staleToolIds'>;

/**
 * Builds the template deps from the main mock's stores, so creating from a template does the same bookkeeping
 * as agents.create (version 1, snapshot, tool grants) without a second copy of it in mock/index.ts.
 */
export function templateDeps(s: {
  agents: AgentRecord[];
  tools: Tool[];
  toolInTeam: (t: Tool) => boolean;
  versions: Record<string, Version[]>;
  snapAgent: (a: AgentRecord) => unknown;
  me: string;
  kbNames: () => string[];
  addCase: TemplatesDeps['addCase'];
  reviews: TemplatesDeps['reviews'];
  skills: TemplatesDeps['skills'];
}): TemplatesDeps {
  return {
    me: s.me,
    kbNames: s.kbNames,
    addCase: s.addCase,
    reviews: s.reviews,
    skills: s.skills,
    // The same scope as tools.list: anything else needs an approval from the module owner first (spec 03).
    teamTools: () => s.tools.filter((t) => t.enabled && s.toolInTeam(t)),
    insertAgent: (fields, note) => {
      const slug = fields.name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
      if (s.agents.some((a) => a.slug === slug)) throw new ApiError(`An agent with the handle ${slug} already exists.`, 409);
      const now = new Date().toISOString();
      const a: AgentRecord = { id: id('ag'), slug, ...fields, paused: false, version: 1, updatedAt: now, tasks24h: 0, autoResolvedRate: 0, workflowIds: [] };
      s.agents.unshift(a);
      for (const t of s.tools) if (fields.toolIds.includes(t.id)) t.grantedAgentIds = [...new Set([...t.grantedAgentIds, a.id])];
      s.versions[a.id] = [{ version: 1, publishedAt: now, publishedBy: s.me, note, changes: [note], current: true }];
      s.snapAgent(a);
      return a;
    },
    agentContent: (aid) => {
      const a = s.agents.find((x) => x.id === aid) ?? notFound('Agent');
      const held = s.tools.filter((t) => a.toolIds.includes(t.id));
      return { ...a, toolNames: held.map((t) => t.name), toolAccess: Object.fromEntries(held.map((t) => [t.name, t.access])) };
    },
  };
}

/** Agent templates. Published ones are visible to every team; submissions only to the team that sent them and Platform. */
export function createTemplatesMock(deps: TemplatesDeps) {
  const templates: (AgentTemplateDetail & { submittedTeam?: string })[] = TEMPLATE_SEEDS.map((s) => ({
    ...s,
    status: 'published',
    ownerTeam: 'Platform',
    starterTestCount: s.starterTests.length,
    missingKnowledge: [],
    unavailableTools: [],
    suggestedSkills: [],
  }));
  const isOpen = (r: Review) => r.status === 'pending' || r.status === 'in_review';
  let seq = 4200;

  const visible = () => templates.filter((t) => t.status === 'published' || inTeam(t.submittedTeam));
  const detail = (t: AgentTemplateDetail): AgentTemplateDetail => {
    const kbs = deps.kbNames();
    const tools = deps.teamTools().map((x) => x.name);
    return { ...t, missingKnowledge: t.expectedKnowledge.filter((k) => !kbs.includes(k)), unavailableTools: t.expectedTools.map((x) => x.name).filter((n) => !tools.includes(n)), suggestedSkills: suggestionsOf(t) };
  };
  /** Seeded suggestions resolve their names from the skills store; a submission carries its own. */
  const suggestionsOf = (t: AgentTemplateDetail): TemplateSkillSuggestion[] =>
    t.suggestedSkills.length
      ? t.suggestedSkills
      : (TEMPLATE_SKILLS[t.id] ?? []).flatMap((x) => {
          const name = deps.skills.name(x.skillId);
          return name ? [{ ...x, name }] : [];
        });
  const row = (t: AgentTemplateDetail): AgentTemplate => {
    const { description: _d, instructions: _i, guardrails: _g, example: _e, starterTests: _s, versions: _v, missingKnowledge: _m, unavailableTools: _u, suggestedSkills: _k, ...r } = t;
    return r;
  };


  type Stored = (typeof templates)[number];

  /** Fields where the template generalises or departs from the agent it copies. */
  function diffOf(t: Stored, a: ReturnType<TemplatesDeps['agentContent']>): TemplateDiffRow[] {
    const rows: TemplateDiffRow[] = [
      { field: 'Name', agent: a.name, template: t.name },
      { field: 'Owner', agent: a.owner, template: 'Platform team, once published' },
      { field: 'Tools', agent: a.toolNames.length ? `Granted: ${a.toolNames.join(', ')}` : 'None', template: t.expectedTools.length ? `Expected: ${t.expectedTools.map((x) => x.name).join(', ')}` : 'None' },
      { field: 'Knowledge bases', agent: a.collections.join(', ') || 'None', template: t.expectedKnowledge.length ? `Expected: ${t.expectedKnowledge.join(', ')}` : 'None' },
      { field: 'Skills', agent: t.suggestedSkills.map((x) => x.name).join(', ') || 'None', template: t.suggestedSkills.length ? `Suggested: ${t.suggestedSkills.map((x) => x.name).join(', ')}` : 'None' },
      { field: 'Starter tests', agent: 'Agent evals', template: 'None; evals and customer data are not copied' },
    ];
    if (a.instructions !== t.instructions) rows.push({ field: 'Instructions', agent: `${a.instructions.length.toLocaleString()} characters`, template: `${t.instructions.length.toLocaleString()} characters` });
    else rows.push({ field: 'Instructions', agent: 'Copied unchanged', template: 'Copied unchanged' });
    return rows;
  }

  /** `source` builds the template from an earlier version of the agent, as when the agent has changed since it was submitted. */
  function submitTemplate(agentId: string, input: { name: string; category: Stored['category']; summary: string; note: string }, by: string, at: string, team?: string, source?: { version: number; instructions: string }): Stored {
    const a = { ...deps.agentContent(agentId), ...source };
    const name = input.name.trim();
    if (!name) throw new ApiError('Name the template.', 400);
    const sentBy = team ?? teamOwner() ?? a.owner;
    // A rejected or returned submission from the same team is replaced, so the team can fix it and send it again.
    const taken = templates.find((t) => t.name.toLowerCase() === name.toLowerCase());
    if (taken && !(taken.status === 'rejected' && taken.submittedTeam === sentBy)) throw new ApiError(`A template named ${name} already exists.`, 409);
    if (taken) templates.splice(templates.indexOf(taken), 1);
    if (deps.reviews().some((r) => r.kind === 'template_submission' && isOpen(r) && r.templateSubmission?.sourceAgentId === agentId)) throw new ApiError(`${a.name} already has a template in review. Wait for the decision first.`, 409);
    const t: Stored = {
      id: id('tpl'),
      name,
      category: input.category,
      summary: input.summary.trim(),
      description: input.summary.trim(),
      version: 1,
      status: 'in_review',
      ownerTeam: sentBy,
      submittedTeam: sentBy,
      submittedBy: by,
      riskTier: a.toolNames.some((n) => /hold|credit|transfer|issue/.test(n)) ? 'high' : a.toolNames.length > 1 ? 'medium' : 'low',
      role: a.role,
      model: a.model,
      channels: a.channels,
      expectedTools: a.toolNames.map((n) => ({ name: n, purpose: 'Granted on the source agent', access: a.toolAccess[n] ?? 'read' })),
      expectedKnowledge: a.collections,
      instructions: a.instructions,
      guardrails: structuredClone(a.guardrails),
      example: { input: '—', output: '—' },
      starterTests: [],
      starterTestCount: 0,
      agentCount: 0,
      updatedAt: at,
      versions: [{ version: 1, note: input.note.trim() || `From ${a.name} v${a.version}`, publishedAt: at, publishedBy: by }],
      missingKnowledge: [],
      unavailableTools: [],
      suggestedSkills: deps.skills.pinnedOn(agentId),
    };
    templates.push(t);
    const req: TemplateSubmissionRequest = {
      templateId: t.id,
      templateName: t.name,
      category: t.category,
      summary: t.summary,
      riskTier: t.riskTier,
      note: input.note.trim(),
      submittedBy: by,
      submittedTeam: sentBy,
      sourceAgentId: agentId,
      sourceAgentName: a.name,
      sourceVersion: a.version,
      agentVersionNow: a.version,
      content: { role: t.role, model: t.model, channels: t.channels, instructions: t.instructions, guardrails: t.guardrails, expectedTools: t.expectedTools, expectedKnowledge: t.expectedKnowledge, suggestedSkills: t.suggestedSkills },
      diff: diffOf(t, a),
    };
    deps.reviews().unshift({
      id: `TPL-${++seq}`,
      title: `Publish template ${t.name}`,
      customer: `Submitted by ${by}`,
      workflowId: '',
      workflowName: t.name,
      agentSlug: '',
      kind: 'template_submission',
      risk: t.riskTier,
      confidence: 1,
      proposal: req.note || t.summary,
      actionTool: 'publish_template',
      currency: 'CAD',
      policy: { id: 'gp_template', name: 'Template publish', condition: 'a team offers an agent as a template for every team', reviewers: 'Platform team', sla: '3 business days', onTimeout: 'Stays pending; the submitter is notified', fourEyes: false },
      slaMinutes: 24 * 60 - Math.round((Date.now() - new Date(at).getTime()) / 60_000),
      approvals: [],
      status: 'pending',
      createdAt: at,
      reasoning: [`Copies ${a.name} v${a.version}`, `${t.category} · ${t.riskTier} risk`],
      evidence: [],
      templateSubmission: req,
    });
    auditSink.log({ action: 'created', target: { type: 'template', name: t.name, href: '/agents?tab=templates' }, summary: `Submitted ${a.name} v${a.version} as a template`, owner: sentBy });
    return t;
  }

  // One submission from another team waits in the queue so the platform team has something to decide.
  // It was sent from the agent's previous version, so the reviewer sees the instructions change made since.
  {
    const a = deps.agentContent('ag_dispute');
    const before = `${a.instructions}\n\nAsk for the receipt before proposing a credit.`;
    submitTemplate('ag_dispute', { name: 'Card dispute intake', category: 'Intake and triage', summary: 'Matches a card dispute to a reason code and gathers the transaction evidence it needs.', note: 'Card Services has run this for four months; 72% of disputes resolve without a hand-off.' }, 'Daniel Brooks', new Date(Date.now() - 21 * 3_600_000).toISOString(), 'Card Services', { version: Math.max(1, a.version - 1), instructions: before });
  }

  /** The submission with the source agent's current version, so the reviewer sees if the agent moved on. */
  function fresh(r: Review): Review {
    const ts = r.templateSubmission;
    if (!ts) return r;
    try {
      const a = deps.agentContent(ts.sourceAgentId);
      return { ...r, templateSubmission: { ...ts, agentVersionNow: a.version, agentInstructionsNow: a.instructions !== ts.content.instructions ? a.instructions : undefined } };
    } catch {
      return r;
    }
  }

  function decide(r: Review, input: ReviewDecisionInput): Review {
    const ts = r.templateSubmission!;
    if (!isOpen(r)) throw new ApiError(`${r.id} was already decided.`, 409);
    if (teamDirectory.current().scope !== 'all') throw new ApiError('Only the platform team decides template submissions. Switch to Platform to decide.', 403);
    if (input.decision !== 'approved' && !input.reason?.trim()) throw new ApiError('A reason is required to reject or return.', 400);
    const t = templates.find((x) => x.id === ts.templateId) ?? notFound('Template');
    const now = new Date().toISOString();
    if (input.decision === 'approved') {
      if (ts.submittedBy === deps.me) throw new ApiError('You submitted this template. Someone else on the platform team must approve it.', 409);
      Object.assign(t, { status: 'published', ownerTeam: 'Platform', updatedAt: now, versions: [{ ...t.versions[0], publishedAt: now, publishedBy: deps.me }] });
      Object.assign(r, { status: 'approved', decidedAt: now, decisionReason: input.reason, assignee: deps.me, approvals: [deps.me] });
      auditSink.log({ action: 'published', target: { type: 'template', name: t.name, href: '/agents?tab=templates' }, summary: `Published template ${t.name} v1`, owner: ts.submittedTeam, reason: input.reason });
      return fresh(r);
    }
    t.status = 'rejected';
    Object.assign(r, { status: input.decision, decidedAt: now, decisionReason: input.reason, assignee: r.assignee ?? deps.me });
    auditSink.log({ action: 'rejected', target: { type: 'template', name: t.name, href: '/agents?tab=templates' }, summary: `${input.decision === 'rejected' ? 'Rejected' : 'Returned'} template ${t.name}`, owner: ts.submittedTeam, reason: input.reason });
    return fresh(r);
  }

  const wrapReviews = (inner: OpsApi['reviews']): OpsApi['reviews'] => ({
    ...inner,
    // The queue's sheet renders the list row, so rows carry the same freshness as `get`.
    list: async (p) => {
      const res = await inner.list(p);
      return { ...res, data: res.data.map((r) => (r.kind === 'template_submission' ? fresh(r) : r)) };
    },
    get: async (rid) => {
      const r = await inner.get(rid);
      return r.kind === 'template_submission' ? fresh(r) : r;
    },
    decide: async (rid, input) => {
      const r = deps.reviews().find((x) => x.id === rid);
      if (r?.kind === 'template_submission') return respond(() => decide(r, input));
      return inner.decide(rid, input);
    },
    bulkDecide: async (ids, decision, reason, opts) => {
      const mine = ids.filter((rid) => deps.reviews().find((x) => x.id === rid)?.kind === 'template_submission');
      const rest = ids.filter((rid) => !mine.includes(rid));
      const res: BulkResult = rest.length ? await inner.bulkDecide(rest, decision, reason, opts) : { updated: [], skipped: [] };
      return { updated: res.updated, skipped: [...res.skipped, ...mine.map((rid) => ({ id: rid, reason: 'Template submissions need an individual decision' }))] };
    },
  });

  const api: TemplatesApi = {
    list: (p) => respond((m) => list(visible().map(row), p, { text: (t) => `${t.name} ${t.summary} ${t.category}`, value: field, facetKeys: ['category', 'riskTier', 'status'] }, m)),
    get: (tid) => respond(() => detail(visible().find((t) => t.id === tid) ?? notFound('Template'))),
    createAgent: async (input: CreateFromTemplateInput) => {
      const created = await respond(() => {
        const t = templates.find((x) => x.id === input.templateId && x.status === 'published') ?? notFound('Template');
        if (input.templateVersion !== t.version) throw new ApiError(`${t.name} has a newer version (v${t.version}). Reopen the template to use it.`, 409);
        if (!input.name.trim()) throw new ApiError('Name the agent.', 400);
        const allowed = deps.teamTools().map((x) => x.id);
        const outside = input.toolIds.filter((x) => !allowed.includes(x));
        if (outside.length) throw new ApiError('One or more tools are not available to your team. Remove them or ask the tool owner for access.', 403);
        const pins = input.skills ?? [];
        deps.skills.check({ ownerTeam: input.owner, toolIds: input.toolIds, knowledgeBases: input.collections }, pins);
        const a = deps.insertAgent(
          { name: input.name.trim(), role: t.role || input.name.trim(), model: input.model, owner: input.owner, channels: t.channels, instructions: input.instructions, toolIds: input.toolIds, collections: input.collections, guardrails: input.guardrails },
          `Created from ${t.name} v${t.version}${pins.length ? ` with ${pins.length === 1 ? '1 skill' : `${pins.length} skills`}` : ''}`,
        );
        deps.skills.add(a.id, pins);
        t.agentCount += 1;
        return { agentId: a.id, agentName: a.name, tests: input.includeStarterTests ? t.starterTests : [], skills: pins.length };
      });
      // Starter tests are written through the evals API so they land in the agent's own test set.
      await Promise.all(created.tests.map((c) => deps.addCase(created.agentId, { ...c, context: { ...c.context, collections: c.context.collections.filter((k) => input.collections.includes(k)) } })));
      return { agentId: created.agentId, agentName: created.agentName, testsAdded: created.tests.length, skillsAttached: created.skills };
    },
    submit: (input) =>
      respond(() => {
        const t = submitTemplate(input.agentId, input, deps.me, new Date().toISOString());
        return row(t);
      }),
  };
  return { api, wrapReviews };
}
